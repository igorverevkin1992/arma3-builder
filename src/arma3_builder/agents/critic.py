"""Critic Agent — advisory-only design review.

Reads the full ``CampaignPlan`` after generation and emits ``CriticNote``s
surfacing design-quality concerns the mechanical QA can't catch:

  A3B401 — All missions end with the same end_type (monotony).
  A3B402 — Enemy-to-player ratio extreme (< 1:1 or > 5:1).
  A3B403 — Zero diary entries across the whole campaign (no narrative).
  A3B404 — No tutorial cue on mission 1 (no cutscene, no intro dialog).
  A3B405 — Single-mission "campaign" with no arc.
  A3B406 — No dialogue across the campaign (immersion gap).
  A3B407 — No character carried across missions (missed arc potential).

Non-blocking: these show up as a separate panel in the UI. Designers can
ignore them but shouldn't.
"""
from __future__ import annotations

from ..config import get_settings
from ..llm.prompts import CRITIC_SYSTEM
from ..protocols import CampaignPlan, CriticNote
from .base import Agent, AgentContext


class CriticAgent(Agent):
    role = "critic"

    def __init__(self) -> None:
        super().__init__(model=get_settings().model_qa)

    async def run(self, plan: CampaignPlan, ctx: AgentContext) -> list[CriticNote]:
        notes = _heuristic_critique(plan)

        # LLM pass is optional: if a real provider is configured, ask it
        # for extra notes. We never block on it — heuristics alone cover
        # the baseline. Stub provider short-circuits to heuristics only.
        if ctx.llm.provider != "stub":
            try:
                extra = await self._llm_critique(plan, ctx)
                notes.extend(extra)
            except Exception as exc:  # noqa: BLE001
                self.log.warning("critic_llm_failed", error=str(exc))

        return notes

    async def _llm_critique(
        self, plan: CampaignPlan, ctx: AgentContext
    ) -> list[CriticNote]:
        user = plan.model_dump_json()
        rsp = await ctx.llm.complete(
            model=self.model, system=CRITIC_SYSTEM, user=user,
            json_mode=True, temperature=0.4, max_tokens=1200,
            role=self.role,
        )
        try:
            data = rsp.parse_json()
        except Exception:  # noqa: BLE001
            return []
        items = data if isinstance(data, list) else data.get("notes", [])
        out: list[CriticNote] = []
        for i, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            out.append(CriticNote(
                code=item.get("code", f"A3B49{i}"),
                severity=item.get("severity", "info"),
                mission_id=item.get("mission_id"),
                message=item.get("message", ""),
                suggestion=item.get("suggestion", ""),
            ))
        return out


# --------------------------------------------------------------------------- #
# Heuristic rules
# --------------------------------------------------------------------------- #


def _heuristic_critique(plan: CampaignPlan) -> list[CriticNote]:
    notes: list[CriticNote] = []
    bps = plan.blueprints

    if not bps:
        return notes

    # A3B405 — single mission called a campaign.
    if len(bps) == 1:
        notes.append(CriticNote(
            code="A3B405", severity="info",
            message=(
                "Campaign contains only one mission — consider adding at "
                "least a follow-up debrief mission so the player sees an arc."
            ),
            suggestion="Add a second mission keyed to the first's outcome "
                       "via a WorldFlagWrite.",
        ))

    # A3B401 — identical end_types across all missions.
    end_sets = []
    for bp in bps:
        et = {s.end_type for s in bp.fsm.states if s.is_terminal and s.end_type}
        end_sets.append(et)
    if len(bps) >= 2 and all(e == end_sets[0] for e in end_sets) and end_sets[0]:
        notes.append(CriticNote(
            code="A3B401", severity="warning",
            message=(
                "Every mission shares the same end states — the campaign has "
                "no branching. Players who replay will see the same arc."
            ),
            suggestion="Add at least one mission with a second `end_type` "
                       "(e.g. `end2`) wired to a different next mission.",
        ))

    # A3B402 — enemy-to-player ratio extremes.
    for bp in bps:
        players = sum(1 for u in bp.units if u.is_player)
        enemies = sum(1 for u in bp.units if u.side == bp.brief.enemy_side)
        if players and enemies:
            ratio = enemies / players
            if ratio < 1:
                notes.append(CriticNote(
                    code="A3B402", severity="warning",
                    mission_id=bp.mission_id,
                    message=f"Enemy:player ratio is {ratio:.1f} — mission "
                            "will feel too easy.",
                    suggestion="Add a ReinforcementWave or second composition.",
                ))
            elif ratio > 5:
                notes.append(CriticNote(
                    code="A3B402", severity="warning",
                    mission_id=bp.mission_id,
                    message=f"Enemy:player ratio is {ratio:.1f} — mission "
                            "may be unwinnable.",
                    suggestion="Reduce enemy composition size or add a CAS "
                               "SupportAsset for the players.",
                ))

    # A3B403 — zero diary entries anywhere.
    total_entries = sum(len(bp.diary.entries) for bp in bps)
    if total_entries == 0:
        notes.append(CriticNote(
            code="A3B403", severity="warning",
            message="No diary entries in any mission — players have no "
                    "in-mission context.",
            suggestion="Add at least Situation/Execution entries per mission.",
        ))

    # A3B404 — mission 1 has no tutorial cue (intro cutscene or dialog).
    m1 = bps[0]
    has_intro = any(c.kind == "intro" for c in m1.cutscenes)
    has_dialog = bool(m1.dialogue)
    if not has_intro and not has_dialog:
        notes.append(CriticNote(
            code="A3B404", severity="info",
            mission_id=m1.mission_id,
            message="First mission has no intro cutscene or dialogue — "
                    "players start cold.",
            suggestion="Add a 5-10s intro Cutscene or an HQ Dialogue in "
                       "the initial FSM state.",
        ))

    # A3B406 — zero dialogue lines across the whole campaign.
    total_dialogue = sum(len(bp.dialogue) for bp in bps)
    if total_dialogue == 0:
        notes.append(CriticNote(
            code="A3B406", severity="info",
            message="No radio dialogue anywhere in the campaign.",
            suggestion="Add Dialogue lines tied to state transitions for "
                       "immersion — even placeholder text helps.",
        ))

    # A3B407 — recurring characters absent despite a multi-mission campaign.
    if len(bps) >= 2 and not plan.brief.characters:
        notes.append(CriticNote(
            code="A3B407", severity="info",
            message="No recurring characters declared — Sgt Miller wouldn't "
                    "feel like Sgt Miller between missions.",
            suggestion="Declare at least one Character on the CampaignBrief "
                       "with shared face/voice.",
        ))

    return notes
