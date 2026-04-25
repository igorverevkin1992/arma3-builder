"""Tests for the Gemini LLM provider integration.

We intentionally do NOT hit the real Gemini API. Instead we monkey-patch
``httpx.AsyncClient`` to capture the request shape and return a synthetic
Gemini-style response, so the tests run offline / in CI.
"""
from __future__ import annotations

from typing import Any

import pytest

from arma3_builder.config import get_settings, reset_settings_cache
from arma3_builder.llm.client import LLMClient, _extract_tokens
from arma3_builder.llm.usage import PRICING, estimate_cost

# --------------------------------------------------------------------------- #
# Settings / pricing
# --------------------------------------------------------------------------- #


def test_default_provider_models_are_gemini():
    reset_settings_cache()
    s = get_settings()
    assert s.model_orchestrator.startswith("gemini-")
    assert s.model_narrative.startswith("gemini-")
    assert s.model_scripter.startswith("gemini-")
    assert s.model_config_master.startswith("gemini-")
    assert s.model_qa.startswith("gemini-")


def test_gemini_pricing_present():
    for name in ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"):
        assert name in PRICING, f"{name} missing from PRICING"
        in_p, out_p = PRICING[name]
        assert 0 < in_p < out_p, f"{name} input must be cheaper than output"


def test_gemini_cost_estimate():
    # 1k input + 1k output of pro ≈ $0.01125 — sanity check, don't lock to penny.
    cost = estimate_cost("gemini-2.5-pro", 1000, 1000)
    assert 0.005 < cost < 0.05


# --------------------------------------------------------------------------- #
# Token extraction
# --------------------------------------------------------------------------- #


def test_extract_tokens_handles_gemini_usage_metadata():
    raw = {
        "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
        "usageMetadata": {"promptTokenCount": 42, "candidatesTokenCount": 7},
    }
    in_tok, out_tok = _extract_tokens(raw, "prompt", "ok")
    assert in_tok == 42
    assert out_tok == 7


def test_extract_tokens_falls_back_to_estimate_for_empty_gemini():
    raw = {"candidates": []}  # safety-blocked Gemini responses look like this
    in_tok, out_tok = _extract_tokens(raw, "hello world " * 10, "")
    assert in_tok > 0  # heuristic kicks in
    assert out_tok >= 1


# --------------------------------------------------------------------------- #
# Provider dispatch
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_gemini_call_routes_through_rest(monkeypatch):
    """Verify _gemini() builds the right request and parses the response.

    Patches httpx.AsyncClient.post to capture the call and return a fake
    Gemini-shaped JSON. Asserts on URL, body, parsed text and usage capture.
    """
    captured: dict[str, Any] = {}

    class _FakeResp:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    class _FakeClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        async def post(self, url: str, **kw: Any) -> _FakeResp:
            captured["url"] = url
            captured["params"] = kw.get("params", {})
            captured["body"] = kw.get("json", {})
            return _FakeResp({
                "candidates": [{
                    "content": {"parts": [{"text": '{"hello": "world"}'}]},
                    "finishReason": "STOP",
                }],
                "usageMetadata": {
                    "promptTokenCount": 11,
                    "candidatesTokenCount": 5,
                },
            })

    monkeypatch.setattr("arma3_builder.llm.client.httpx.AsyncClient", _FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-AIza")
    reset_settings_cache()

    client = LLMClient(provider="gemini")
    rsp = await client.complete(
        model="gemini-2.5-flash",
        system="you are a tester",
        user="emit one json object",
        temperature=0.0,
        max_tokens=128,
        json_mode=True,
        role="orchestrator",
    )

    assert rsp.provider == "gemini"
    assert rsp.model == "gemini-2.5-flash"
    assert rsp.parse_json() == {"hello": "world"}
    assert ":generateContent" in captured["url"]
    assert captured["params"] == {"key": "test-key-AIza"}
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "you are a tester"
    assert captured["body"]["contents"][0]["parts"][0]["text"] == "emit one json object"
    assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["body"]["generationConfig"]["temperature"] == 0.0
    assert captured["body"]["generationConfig"]["maxOutputTokens"] == 128


@pytest.mark.asyncio
async def test_gemini_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reset_settings_cache()
    client = LLMClient(provider="gemini")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await client.complete(
            model="gemini-2.5-flash",
            system="s", user="u", role="orchestrator",
        )


@pytest.mark.asyncio
async def test_gemini_safety_block_returns_empty_text(monkeypatch):
    """When Gemini returns no candidates (safety block), we emit empty text
    and let the caller handle the empty-string as a graceful degrade."""
    class _FakeResp:
        def raise_for_status(self) -> None: return None
        def json(self) -> dict[str, Any]:
            return {"promptFeedback": {"blockReason": "SAFETY"}}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, **kw): return _FakeResp()

    monkeypatch.setattr("arma3_builder.llm.client.httpx.AsyncClient", _FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    reset_settings_cache()

    client = LLMClient(provider="gemini")
    rsp = await client.complete(
        model="gemini-2.5-flash",
        system="s", user="u", role="orchestrator",
    )
    assert rsp.text == ""
    assert rsp.provider == "gemini"
