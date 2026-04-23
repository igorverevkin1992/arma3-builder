"""Token / cost tracking for LLM calls.

Every call to ``LLMClient.complete`` is recorded as a ``UsageEvent`` on a
thread-safe accumulator. The pipeline attaches an ``UsageReport`` to the
``GenerationResult`` so the API / UI can show "$0.23 / 3.4s" per run.

Pricing table is intentionally conservative — the idea is to give the
designer a cost order of magnitude, not an accounting receipt. Update the
table when provider pricing changes.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

# Model → (input_per_1k_usd, output_per_1k_usd) snapshot. Keep entries
# conservative; unknown models fall through to zero cost + a "uncosted" tag.
PRICING: dict[str, tuple[float, float]] = {
    # Anthropic (Opus/Sonnet/Haiku). Sonnet mid-tier prices shown.
    "claude-opus-4-7":   (0.015, 0.075),
    "claude-opus-4-6":   (0.015, 0.075),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-sonnet-4-5": (0.003, 0.015),
    "claude-haiku-4-5-20251001": (0.001, 0.005),
    # OpenAI
    "gpt-4o":            (0.005, 0.015),
    "gpt-4o-mini":       (0.00015, 0.0006),
    # Local Ollama — cost is zero but we still count tokens for analytics.
    "llama3:8b":         (0.0, 0.0),
    "llama3:70b":        (0.0, 0.0),
}


@dataclass
class UsageEvent:
    provider: str
    model: str
    role: str                  # which agent called
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "role": self.role,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
        }


@dataclass
class UsageReport:
    events: list[UsageEvent] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(e.input_tokens for e in self.events)

    @property
    def total_output_tokens(self) -> int:
        return sum(e.output_tokens for e in self.events)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(e.cost_usd for e in self.events), 6)

    @property
    def total_latency_ms(self) -> int:
        return sum(e.latency_ms for e in self.events)

    def by_role(self) -> dict[str, dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for e in self.events:
            b = buckets.setdefault(e.role, {
                "input_tokens": 0, "output_tokens": 0,
                "cost_usd": 0.0, "calls": 0, "latency_ms": 0,
            })
            b["input_tokens"] += e.input_tokens
            b["output_tokens"] += e.output_tokens
            b["cost_usd"] += e.cost_usd
            b["latency_ms"] += e.latency_ms
            b["calls"] += 1
        for v in buckets.values():
            v["cost_usd"] = round(v["cost_usd"], 6)
        return buckets

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": self.total_cost_usd,
            "total_latency_ms": self.total_latency_ms,
            "calls": len(self.events),
            "by_role": self.by_role(),
            "events": [e.to_dict() for e in self.events],
        }


class UsageAccumulator:
    """Thread-safe counter used by ``LLMClient``.

    A single module-level instance is shared; the pipeline snapshots and
    resets it per request so concurrent generations don't mix numbers.
    """
    def __init__(self) -> None:
        self._events: list[UsageEvent] = []
        self._lock = threading.Lock()

    def record(self, event: UsageEvent) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> UsageReport:
        with self._lock:
            return UsageReport(events=list(self._events))

    def drain(self) -> UsageReport:
        with self._lock:
            out = UsageReport(events=list(self._events))
            self._events.clear()
            return out


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING.get(model)
    if p is None:
        return 0.0
    return (input_tokens / 1000.0) * p[0] + (output_tokens / 1000.0) * p[1]


def estimate_tokens_from_text(text: str) -> int:
    """Cheap token estimator: ~4 chars per token (English). Good enough
    for Ollama and the stub provider where no token counts are returned."""
    return max(1, len(text) // 4)
