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
            role=self.role,
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
        from ..arma.campaign import slugify
        blueprints = []
        for i, m in enumerate(brief.missions):
            bp = self._fallback_blueprint(m, brief, ctx, index=i)
            bp.mission_id = f"m{i + 1:02d}_{slugify(m.title)}"
            blueprints.append(bp)
        return CampaignPlan(brief=brief, blueprints=blueprints)

    def _fallback_blueprint(
        self, mission: MissionBrief, brief: CampaignBrief, ctx: AgentContext,
        *, index: int = 0,
    ) -> MissionBlueprint:
        # Insertion -> Movement -> Engagement -> Extraction. Predicates use
        # entities the SQM definitely contains (named units p1, e1) and a
        # short timer for the "insertion finished" gate, so the mission is
        # actually playable end-to-end without external setup.
        fsm = FsmGraph(
            initial="insertion",
            on_enter_global=[
                "A3B_target = e1",
                "A3B_lzPos = position p1",
            ],
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
                            kind=TransitionKind.TIMER,
                            condition="20",
                            description="Insertion considered complete after 20s",
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
                            kind=TransitionKind.TRIGGER,
                            condition="(player distance A3B_target) < 250",
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
                            condition='({alive _x && {side _x == east}} count allUnits) == 0',
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
        # Resolve classnames: prefer RAG (mod-aware, filtered by tenant/faction),
        # then registry, finally hardcoded vanilla.
        west_class = self._pick_rifleman(
            ctx, side=mission.side, faction=brief.factions.get(mission.side),
            tenants=brief.mods, fallback="B_Soldier_F",
        )
        east_class = self._pick_rifleman(
            ctx, side=mission.enemy_side, faction=brief.factions.get(mission.enemy_side),
            tenants=brief.mods, fallback="O_Soldier_F",
        )

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

    def _pick_rifleman(
        self,
        ctx: AgentContext,
        *,
        side: str,
        faction: str | None,
        tenants: list[str],
        fallback: str,
    ) -> str:
        """RAG-first classname resolution.

        Order of preference:
          1. RAG hybrid search filtered by tenant+side+type=Man (mod-aware)
          2. Classname registry filter (in-process seed data)
          3. Fallback vanilla classname
        """
        # 1) RAG
        try:
            hits = ctx.retriever.classnames(
                query=faction or f"{side} rifleman soldier",
                type="Man",
                side=side,
                tenants=tenants or None,
                k=1,
            )
            if hits:
                return hits[0].metadata.get("classname", fallback)
        except Exception:  # noqa: BLE001  — RAG must never crash generation
            pass
        # 2) Registry
        for info in ctx.registry.filter(side=side, type="Man"):
            return info.classname
        # 3) Fallback
        return fallback
