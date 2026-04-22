"""Narrative Director: builds the FSM graph + diary for each mission."""
from __future__ import annotations

from ..config import get_settings
from ..llm.prompts import NARRATIVE_SYSTEM
from ..protocols import (
    BriefingEntry,
    CampaignBrief,
    CampaignPlan,
    Diary,
    FsmGraph,
    FsmState,
    FsmTransition,
    MissionBlueprint,
    MissionBrief,
    TransitionKind,
    UnitPlacement,
    Waypoint,
)
from .base import Agent, AgentContext


class NarrativeAgent(Agent):
    role = "narrative"

    def __init__(self) -> None:
        super().__init__(model=get_settings().model_narrative)

    async def run(self, brief: CampaignBrief, ctx: AgentContext) -> CampaignPlan:
        rsp = await self.llm(ctx).complete(
            model=self.model,
            system=NARRATIVE_SYSTEM,
            user=brief.model_dump_json(),
            json_mode=True,
            temperature=0.5,
        )
        if rsp.provider == "stub":
            return self._fallback_plan(brief, ctx)
        try:
            data = rsp.parse_json()
            return CampaignPlan.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("narrative_parse_failed", error=str(exc))
            return self._fallback_plan(brief, ctx)

    # -------------------------------------------------------------- fallback

    def _fallback_plan(self, brief: CampaignBrief, ctx: AgentContext) -> CampaignPlan:
        blueprints = [self._fallback_blueprint(m, brief, ctx) for m in brief.missions]
        return CampaignPlan(brief=brief, blueprints=blueprints)

    def _fallback_blueprint(
        self, mission: MissionBrief, brief: CampaignBrief, ctx: AgentContext
    ) -> MissionBlueprint:
        # Choose a deterministic FSM matching the canonical pattern from the TZ:
        # Insertion -> Movement -> Engagement -> Extraction.
        fsm = FsmGraph(
            initial="insertion",
            states=[
                FsmState(
                    id="insertion",
                    label="Insertion",
                    on_enter=[
                        'titleText ["Insertion in progress","BLACK FADED"]',
                    ],
                    transitions=[
                        FsmTransition(
                            to="movement",
                            kind=TransitionKind.TRIGGER,
                            condition="!isNil 'A3B_insertionDone' && {A3B_insertionDone}",
                            description="Players past insertion zone",
                        ),
                    ],
                ),
                FsmState(
                    id="movement",
                    label="Approach",
                    on_enter=[
                        '["task_main","ASSIGNED"] call BIS_fnc_taskSetState',
                    ],
                    transitions=[
                        FsmTransition(
                            to="engagement",
                            kind=TransitionKind.OBJECTIVE,
                            condition="(missionNamespace getVariable ['A3B_contact', false])",
                        ),
                    ],
                ),
                FsmState(
                    id="engagement",
                    label="Engagement",
                    on_enter=[
                        '["task_main","SUCCEEDED"] call BIS_fnc_taskSetState',
                    ],
                    transitions=[
                        FsmTransition(
                            to="extraction",
                            kind=TransitionKind.TRIGGER,
                            condition="!alive (missionNamespace getVariable ['A3B_target', objNull])",
                        ),
                        FsmTransition(
                            to="failure",
                            kind=TransitionKind.TRIGGER,
                            condition="({alive _x} count units (group player)) == 0",
                        ),
                    ],
                ),
                FsmState(
                    id="extraction",
                    label="Extraction",
                    on_enter=[],
                    is_terminal=True,
                    end_type="end1",
                ),
                FsmState(
                    id="failure",
                    label="Failed",
                    on_enter=[],
                    is_terminal=True,
                    end_type="loser",
                ),
            ],
        )

        units = self._fallback_units(mission, brief, ctx)
        wps = [
            Waypoint(group_id="player", position=(150.0, 150.0, 0.0), type="MOVE"),
            Waypoint(group_id="enemy", position=(180.0, 200.0, 0.0), type="GUARD", behaviour="COMBAT"),
        ]
        diary = Diary(
            entries=[
                BriefingEntry(tab="Situation", title="Situation", text=mission.summary),
                BriefingEntry(
                    tab="Mission",
                    title="Objectives",
                    text="<br/>".join(f"- {o}" for o in mission.objectives),
                ),
                BriefingEntry(tab="Execution", title="Execution",
                              text="Move to the objective, neutralise the threat, extract."),
            ],
            tasks=[
                {
                    "id": "task_main",
                    "title": mission.objectives[0] if mission.objectives else "Main objective",
                    "description": mission.objectives[0] if mission.objectives else "Complete the mission",
                    "marker": "objective",
                    "state": "ASSIGNED",
                }
            ],
        )

        return MissionBlueprint(
            brief=mission,
            fsm=fsm,
            units=units,
            waypoints=wps,
            diary=diary,
            addons=brief.mods,
        )

    def _fallback_units(
        self, mission: MissionBrief, brief: CampaignBrief, ctx: AgentContext
    ) -> list[UnitPlacement]:
        # Try the registry; fall back to vanilla classes.
        west_class = "B_Soldier_F"
        east_class = "O_Soldier_F"
        for info in ctx.registry.filter(side="WEST", type="Man"):
            west_class = info.classname
            break
        for info in ctx.registry.filter(side="EAST", type="Man"):
            east_class = info.classname
            break

        units: list[UnitPlacement] = []
        for i in range(max(1, mission.player_count)):
            units.append(UnitPlacement(
                classname=west_class,
                side=mission.side,
                position=(100.0 + i * 5, 100.0, 0.0),
                direction=0.0,
                name=f"p{i + 1}",
                is_player=True,
                is_leader=(i == 0),
                group_id="player",
            ))
        for i in range(4):
            units.append(UnitPlacement(
                classname=east_class,
                side=mission.enemy_side,
                position=(200.0 + i * 4, 200.0, 0.0),
                direction=180.0,
                name=f"e{i + 1}",
                group_id="enemy",
            ))
        return units
