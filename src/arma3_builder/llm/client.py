"""Multi-provider LLM client with a stub fallback for offline / CI runs."""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import ProviderName, get_settings
from ..utils.logger import get_logger
from .usage import (
    UsageAccumulator,
    UsageEvent,
    estimate_cost,
    estimate_tokens_from_text,
)

logger = get_logger(__name__)


# Module-level accumulator. The pipeline snapshots and resets it per
# generation — see ``Pipeline.generate_from_plan``.
usage_accumulator = UsageAccumulator()


@dataclass
class LLMResponse:
    text: str
    raw: dict[str, Any]
    model: str
    provider: ProviderName

    def parse_json(self) -> Any:
        """Try to parse the response as JSON, tolerating ```json fences."""
        text = self.text.strip()
        if text.startswith("```"):
            # strip leading ```json or ```
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text[: -3]
            text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)


class LLMClient:
    """Provider-agnostic chat client.

    The system uses different models per agent role (large/contextual for
    Orchestrator+Narrative, smaller for Scripter, local for QA). This client
    is responsible for routing to the right provider based on the model name.
    """

    def __init__(self, *, provider: ProviderName | None = None) -> None:
        s = get_settings()
        self.provider: ProviderName = provider or s.llm_provider

    async def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
        role: str = "unknown",
    ) -> LLMResponse:
        started = time.monotonic()
        if self.provider == "stub":
            rsp = await self._stub(model=model, system=system, user=user, json_mode=json_mode)
        elif self.provider == "anthropic":
            rsp = await self._anthropic(model, system, user, temperature, max_tokens, json_mode)
        elif self.provider == "openai":
            rsp = await self._openai(model, system, user, temperature, max_tokens, json_mode)
        elif self.provider == "ollama":
            rsp = await self._ollama(model, system, user, temperature, max_tokens, json_mode)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

        # Best-effort token / cost capture. Raw response shapes vary, so we
        # probe several known fields and fall back to a length-based estimate.
        elapsed_ms = int((time.monotonic() - started) * 1000)
        in_tok, out_tok = _extract_tokens(rsp.raw, system + user, rsp.text)
        cost = estimate_cost(model, in_tok, out_tok)
        usage_accumulator.record(UsageEvent(
            provider=self.provider, model=model, role=role,
            input_tokens=in_tok, output_tokens=out_tok,
            cost_usd=cost, latency_ms=elapsed_ms,
        ))
        return rsp

    # ------------------------------------------------------------------ providers

    async def _anthropic(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("anthropic package not installed") from exc

        api_key = get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")

        client = anthropic.AsyncAnthropic(api_key=api_key)
        if json_mode:
            user = user + "\n\nReturn ONLY a JSON object — no prose, no code fences."
        msg = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in msg.content if hasattr(block, "text"))
        return LLMResponse(text=text, raw=msg.model_dump(), model=model, provider="anthropic")

    async def _openai(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        try:
            from openai import AsyncOpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("openai package not installed") from exc

        api_key = get_settings().openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")

        client = AsyncOpenAI(api_key=api_key)
        kwargs: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        rsp = await client.chat.completions.create(**kwargs)
        text = rsp.choices[0].message.content or ""
        return LLMResponse(text=text, raw=rsp.model_dump(), model=model, provider="openai")

    async def _ollama(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        base = get_settings().ollama_base_url
        async with httpx.AsyncClient(base_url=base, timeout=120) as http:
            payload = {
                "model": model,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if json_mode:
                payload["format"] = "json"
            r = await http.post("/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            text = data.get("message", {}).get("content", "")
            return LLMResponse(text=text, raw=data, model=model, provider="ollama")

    async def _stub(
        self, *, model: str, system: str, user: str, json_mode: bool
    ) -> LLMResponse:
        """Deterministic stub used in tests / offline runs.

        Returns a minimal but well-formed JSON envelope so the pipeline can
        execute without an external LLM. Real providers replace this in prod.
        """
        await asyncio.sleep(0)  # keep coroutine semantics
        echo = {"system_excerpt": system[:120], "user_excerpt": user[:160], "model": model}
        text = json.dumps(echo) if json_mode else f"[stub:{model}] {user[:80]}"
        return LLMResponse(text=text, raw=echo, model=model, provider="stub")


def _extract_tokens(raw: dict, prompt_text: str, reply_text: str) -> tuple[int, int]:
    """Pull input/output token counts from a raw provider response.

    Each SDK puts the counts in a slightly different spot. When nothing is
    exposed (Ollama older versions, stub), we estimate from text length so
    the cost column is never empty.
    """
    # Anthropic: raw["usage"] = {"input_tokens": N, "output_tokens": M}
    u = raw.get("usage") if isinstance(raw, dict) else None
    if isinstance(u, dict):
        in_tok = (u.get("input_tokens")
                  or u.get("prompt_tokens")
                  or u.get("prompt_eval_count")
                  or 0)
        out_tok = (u.get("output_tokens")
                   or u.get("completion_tokens")
                   or u.get("eval_count")
                   or 0)
        if in_tok or out_tok:
            return int(in_tok), int(out_tok)
    # Ollama: top-level prompt_eval_count / eval_count
    if isinstance(raw, dict):
        in_tok = raw.get("prompt_eval_count", 0)
        out_tok = raw.get("eval_count", 0)
        if in_tok or out_tok:
            return int(in_tok), int(out_tok)
    return estimate_tokens_from_text(prompt_text), estimate_tokens_from_text(reply_text)


_client_singleton: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = LLMClient()
    return _client_singleton
