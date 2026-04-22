"""QA Validator: runs the analyser and emits a structured report.

If the configured QA model is a local Ollama model, an additional pass can
review residual warnings, but the primary signal comes from the deterministic
linter+analyser pipeline (which is what the Scripter's repair() consumes).
"""
from __future__ import annotations

from ..config import get_settings
from ..protocols import (
    CampaignPlan,
    GeneratedArtifact,
    QAReport,
)
from ..qa.analyzer import build_qa_report
from .base import Agent, AgentContext


class QAAgent(Agent):
    role = "qa"

    def __init__(self) -> None:
        super().__init__(model=get_settings().model_qa)

    async def run(
        self,
        plan: CampaignPlan,
        artifacts: list[GeneratedArtifact],
        ctx: AgentContext,
        *,
        iteration: int,
    ) -> QAReport:
        report = build_qa_report(plan, artifacts, iteration=iteration)
        ctx.memory.setdefault("qa_history", []).append({
            "iteration": iteration,
            "errors": len(report.errors),
            "warnings": len(report.warnings),
        })
        return report
