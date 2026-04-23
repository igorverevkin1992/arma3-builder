"""Orchestrator: parses a free-form designer prompt into a CampaignBrief."""
from __future__ import annotations

import json
import re

from ..config import get_settings
from ..llm.prompts import ORCHESTRATOR_SYSTEM
from ..protocols import CampaignBrief, MissionBrief
from .base import Agent, AgentContext

_BRIEF_SCHEMA = """\
Return a JSON object with this shape:
{
  "name": str,
  "author": str,
  "overview": str,
  "mods": [str],
  "factions": { "WEST": str, "EAST": str, "INDEPENDENT": str },
  "missions": [
    {
      "title": str,
      "summary": str,
      "map": str,
      "side": "WEST"|"EAST"|"INDEPENDENT"|"CIVILIAN",
      "enemy_side": "WEST"|"EAST"|"INDEPENDENT"|"CIVILIAN",
      "objectives": [str],
      "time_of_day": "HH:MM",
      "weather": "clear"|"overcast"|"rain"|"storm",
      "player_count": int,
      "tags": [str]
    }
  ]
}
"""


class OrchestratorAgent(Agent):
    role = "orchestrator"

    def __init__(self) -> None:
        super().__init__(model=get_settings().model_orchestrator)

    async def run(self, prompt: str, ctx: AgentContext) -> CampaignBrief:
        rsp = await self.llm(ctx).complete(
            model=self.model,
            system=ORCHESTRATOR_SYSTEM,
            user=f"{_BRIEF_SCHEMA}\n\nDesigner prompt:\n{prompt}",
            json_mode=True,
            temperature=0.3,
        )
        if rsp.provider == "stub":
            return self._fallback_brief(prompt)
        try:
            data = rsp.parse_json()
        except json.JSONDecodeError as exc:
            self.log.warning("orchestrator_json_parse_failed", error=str(exc))
            return self._fallback_brief(prompt)
        try:
            brief = CampaignBrief.model_validate(data)
        except Exception as exc:  # noqa: BLE001 — pydantic ValidationError
            self.log.warning("orchestrator_schema_validation_failed", error=str(exc))
            return self._fallback_brief(prompt)
        ctx.memory["brief"] = brief.model_dump()
        return brief

    # -------------------------------------------------------------- fallback

    def _fallback_brief(self, prompt: str) -> CampaignBrief:
        title = self._extract_title(prompt)
        return CampaignBrief(
            name=title,
            author="arma3-builder",
            overview=prompt.strip()[:500],
            mods=["cba_main"],
            factions={"WEST": "BLU_F", "EAST": "OPF_F", "INDEPENDENT": "IND_F"},
            missions=[
                MissionBrief(
                    title=f"{title} - Mission 1",
                    summary=prompt.strip()[:280] or "Auto-generated objective.",
                    map=self._guess_map(prompt),
                    side="WEST",
                    enemy_side="EAST",
                    objectives=["Reach the objective", "Eliminate hostiles", "Extract"],
                    time_of_day="06:30",
                    weather="overcast",
                    player_count=1,
                    tags=["auto"],
                )
            ],
        )

    @staticmethod
    def _extract_title(prompt: str) -> str:
        words = re.findall(r"[A-Za-zА-Яа-я0-9]+", prompt)
        if not words:
            return "Untitled Campaign"
        return " ".join(words[:4]).title()

    @staticmethod
    def _guess_map(prompt: str) -> str:
        for needle, world in {
            "tanoa": "Tanoa",
            "altis": "Altis",
            "stratis": "Stratis",
            "malden": "Malden",
            "livonia": "Enoch",
            "chernarus": "Chernarus",
            "takistan": "Takistan",
            "vr": "VR",
        }.items():
            if needle in prompt.lower():
                return world
        return "VR"
