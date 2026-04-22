"""Pydantic schemas for the FastAPI surface."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..protocols import CampaignBrief, CampaignPlan, QAReport


class GenerateRequest(BaseModel):
    prompt: str | None = Field(
        default=None,
        description="Free-form designer prompt. Mutually exclusive with `brief`.",
    )
    brief: CampaignBrief | None = Field(
        default=None,
        description="Skip the Orchestrator stage by supplying a structured brief directly.",
    )
    create_zip: bool = False

    def model_post_init(self, _ctx: Any) -> None:
        if not self.prompt and not self.brief:
            raise ValueError("Either `prompt` or `brief` must be provided")


class GenerateResponse(BaseModel):
    output_path: str | None
    iterations: int
    qa: QAReport
    artifact_count: int
    plan: CampaignPlan


class PreviewResponse(BaseModel):
    """Used by the visual node-graph editor (Phase 4)."""
    plan: CampaignPlan
    fsm_diagrams: list[dict[str, Any]]
