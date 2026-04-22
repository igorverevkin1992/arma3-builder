"""Multi-provider LLM client with a stub fallback for offline / CI runs."""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import ProviderName, get_settings
from ..utils.logger import get_logger

logger = get_logger(__name__)


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
    ) -> LLMResponse:
        if self.provider == "stub":
            return await self._stub(model=model, system=system, user=user, json_mode=json_mode)
        if self.provider == "anthropic":
            return await self._anthropic(model, system, user, temperature, max_tokens, json_mode)
        if self.provider == "openai":
            return await self._openai(model, system, user, temperature, max_tokens, json_mode)
        if self.provider == "ollama":
            return await self._ollama(model, system, user, temperature, max_tokens, json_mode)
        raise ValueError(f"Unsupported provider: {self.provider}")

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


_client_singleton: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = LLMClient()
    return _client_singleton
