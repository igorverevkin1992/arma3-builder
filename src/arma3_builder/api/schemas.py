"""Pydantic schemas for the FastAPI surface."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..protocols import CampaignBrief, CampaignPlan, MissionBlueprint, QAReport


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
    score: dict[str, int] | None = None
    launch: dict[str, Any] | None = None
    diff: list[dict[str, Any]] | None = None
    # Phase-A additions.
    pacing: dict[str, Any] | None = None
    playtest: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None
    # Phase-C additions.
    critic_notes: list[dict[str, Any]] | None = None


class PlanUpdateRequest(BaseModel):
    """Accept a user-edited CampaignPlan + optionally regenerate artefacts."""
    plan: CampaignPlan
    regenerate: bool = True


class SyncFromEdenRequest(BaseModel):
    """Round-trip an Eden-edited mission.sqm back into the blueprint."""
    plan: CampaignPlan
    mission_index: int = 0
    sqm_text: str


class PreviewResponse(BaseModel):
    """Used by the visual node-graph editor (Phase 4)."""
    plan: CampaignPlan
    fsm_diagrams: list[dict[str, Any]]


class RefineRequest(BaseModel):
    plan: CampaignPlan
    instruction: str


class TemplateInstance(BaseModel):
    blueprint: MissionBlueprint
