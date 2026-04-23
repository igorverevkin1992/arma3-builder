"""Catalogue of pre-built mission archetypes.

Each archetype ships an FSM graph, default unit layout, diary stubs and dialog
lines. Designers parameterise them (map, sides, waypoint positions, player
count) instead of writing a brief.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..arma.campaign import slugify
from ..protocols import (
    BriefingEntry,
    Dialogue,
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


@dataclass
class TemplateParameter:
    name: str
    label: str
    kind: str = "string"        # string | int | float | list
    default: object | None = None
    required: bool = False


@dataclass
class MissionTemplate:
    id: str
    label: str
    summary: str
    tags: list[str]
    parameters: list[TemplateParameter]
    factory: Callable[[dict], MissionBlueprint]

    def instantiate(self, params: dict) -> MissionBlueprint:
        merged = {p.name: p.default for p in self.parameters}
        merged.update(params or {})
        return self.factory(merged)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


_COMMON_PARAMS = [
    TemplateParameter("title", "Mission title", "string", "Untitled", required=True),
    TemplateParameter("map", "World class", "string", "VR"),
    TemplateParameter("side", "Player side", "string", "WEST"),
    TemplateParameter("enemy_side", "Enemy side", "string", "EAST"),
    TemplateParameter("player_count", "Player slots", "int", 4),
    TemplateParameter("player_class", "Player classname", "string", "B_Soldier_F"),
    TemplateParameter("enemy_class", "Enemy classname", "string", "O_Soldier_F"),
    TemplateParameter("time_of_day", "Start time HH:MM", "string", "06:30"),
    TemplateParameter("weather", "Weather", "string", "overcast"),
]


def _brief(p: dict, summary: str, objectives: list[str], tags: list[str]) -> MissionBrief:
    return MissionBrief(
        title=p["title"],
        summary=summary,
        map=p["map"],
        side=p["side"],
        enemy_side=p["enemy_side"],
        objectives=objectives,
        time_of_day=p["time_of_day"],
        weather=p["weather"],
        player_count=int(p["player_count"]),
        tags=tags,
    )


def _player_squad(p: dict, origin: tuple[float, float, float]) -> list[UnitPlacement]:
    units: list[UnitPlacement] = []
    for i in range(int(p["player_count"])):
        units.append(UnitPlacement(
            classname=p["player_class"],
            side=p["side"],
            position=(origin[0] + i * 2, origin[1], origin[2]),
            name=f"p{i + 1}",
            is_player=True,
            is_leader=(i == 0),
            group_id="player",
        ))
    return units


def _enemy_group(p: dict, origin: tuple[float, float, float], count: int = 6) -> list[UnitPlacement]:
    return [
        UnitPlacement(
            classname=p["enemy_class"],
            side=p["enemy_side"],
            position=(origin[0] + i * 3, origin[1] + (i % 2) * 2, origin[2]),
            name=f"e{i + 1}",
            group_id="enemy",
        )
        for i in range(count)
    ]


def _mission_id(p: dict) -> str:
    return slugify(p["title"]).lower()


# --------------------------------------------------------------------------- #
# Archetype factories
# --------------------------------------------------------------------------- #


def _convoy(p: dict) -> MissionBlueprint:
    # Predicates target the named enemy `e1` (the lead AI in `_enemy_group`)
    # so the FSM operates on entities the SQM actually contains. No
    # never-set namespace sentinels.
    fsm = FsmGraph(
        initial="depart",
        on_enter_global=[
            "A3B_enemyLead = e1",
            "A3B_lzPos = getMarkerPos \"a3b_lz\"",
        ],
        states=[
            FsmState(
                id="depart", label="Depart FOB",
                on_enter=['["task_move","ASSIGNED"] call BIS_fnc_taskSetState'],
                transitions=[FsmTransition(
                    to="ambush", kind=TransitionKind.TRIGGER,
                    condition="(player distance A3B_enemyLead) < 250",
                )],
            ),
            FsmState(
                id="ambush", label="Ambush",
                transitions=[
                    FsmTransition(
                        to="extract", kind=TransitionKind.TRIGGER,
                        condition='({alive _x && {side _x == east}} count allUnits) == 0',
                    ),
                    FsmTransition(
                        to="failure", kind=TransitionKind.TRIGGER,
                        condition="({alive _x} count units (group player)) == 0",
                    ),
                ],
            ),
            FsmState(
                id="extract", label="Extract",
                on_enter=['["task_move","SUCCEEDED"] call BIS_fnc_taskSetState'],
                is_terminal=True, end_type="end1",
            ),
            FsmState(id="failure", label="Convoy lost", is_terminal=True, end_type="loser"),
        ],
    )
    return MissionBlueprint(
        mission_id=_mission_id(p),
        brief=_brief(
            p,
            summary="Escort the convoy through an ambush corridor.",
            objectives=["Reach the waypoint", "Survive the ambush", "Extract"],
            tags=["convoy", "escort"],
        ),
        fsm=fsm,
        units=_player_squad(p, (100.0, 100.0, 0.0))
              + _enemy_group(p, (250.0, 150.0, 0.0), count=8),
        waypoints=[Waypoint(group_id="player", position=(300.0, 300.0, 0.0), type="MOVE")],
        diary=Diary(entries=[
            BriefingEntry(tab="Situation", title="Threat",
                          text="Partisan activity reported on the route."),
            BriefingEntry(tab="Execution", title="Plan",
                          text="Move, engage on contact, continue to the LZ."),
        ], tasks=[{"id": "task_move", "title": "Reach LZ",
                   "description": "Drive to the extraction LZ", "marker": "lz"}]),
        dialogue=[
            Dialogue(id="hq_contact", speaker="HQ", trigger_state="ambush",
                     text="Hostiles at your position — engage!"),
        ],
    )


def _defend(p: dict) -> MissionBlueprint:
    # "boss" is the lead enemy from the spawn group (e1). Victory = no enemies
    # alive; failure = no friendlies alive. Both predicates only reference
    # entities the SQM definitely contains.
    fsm = FsmGraph(
        initial="prepare",
        on_enter_global=["A3B_waveBoss = e1"],
        states=[
            FsmState(id="prepare", label="Prepare defence",
                     transitions=[FsmTransition(
                         to="hold", kind=TransitionKind.TIMER, condition="60",
                         description="Hold positions after 60s",
                     )]),
            FsmState(
                id="hold", label="Hold the line",
                transitions=[
                    FsmTransition(
                        to="victory", kind=TransitionKind.TRIGGER,
                        condition='({alive _x && {side _x == east}} count allUnits) == 0',
                    ),
                    FsmTransition(
                        to="failure", kind=TransitionKind.TRIGGER,
                        condition="({alive _x} count units (group player)) == 0",
                    ),
                ],
            ),
            FsmState(id="victory", label="Position held", is_terminal=True, end_type="end1"),
            FsmState(id="failure", label="Overrun", is_terminal=True, end_type="loser"),
        ],
    )
    return MissionBlueprint(
        mission_id=_mission_id(p),
        brief=_brief(p, summary="Hold the FOB against waves of attackers.",
                     objectives=["Hold the perimeter", "Eliminate enemy commander"],
                     tags=["defend", "waves"]),
        fsm=fsm,
        units=_player_squad(p, (500.0, 500.0, 0.0))
              + _enemy_group(p, (600.0, 600.0, 0.0), count=10),
        waypoints=[Waypoint(group_id="enemy", position=(520.0, 520.0, 0.0), type="SAD")],
        diary=Diary(entries=[
            BriefingEntry(tab="Situation", title="Incoming",
                          text="Enemy push expected in 60 seconds."),
        ]),
    )


def _sabotage(p: dict) -> MissionBlueprint:
    # The "target" is the lead enemy unit (e1) for the demo. plantDone is
    # set by the player via an addAction the SQM doesn't yet generate;
    # for now the trigger fires when the target is killed.
    fsm = FsmGraph(
        initial="infiltrate",
        on_enter_global=[
            "A3B_target = e1",
            "A3B_lzPos = position p1",
        ],
        states=[
            FsmState(id="infiltrate", label="Infiltrate",
                     transitions=[FsmTransition(
                         to="plant", kind=TransitionKind.TRIGGER,
                         condition="(player distance A3B_target) < 50",
                     )]),
            FsmState(id="plant", label="Plant charges",
                     transitions=[FsmTransition(
                         to="exfil", kind=TransitionKind.TRIGGER,
                         condition="!alive A3B_target",
                     )]),
            FsmState(id="exfil", label="Exfiltrate",
                     transitions=[FsmTransition(
                         to="win", kind=TransitionKind.TRIGGER,
                         condition="(player distance A3B_lzPos) < 50",
                     )]),
            FsmState(id="win", label="Target destroyed", is_terminal=True, end_type="end1"),
        ],
    )
    return MissionBlueprint(
        mission_id=_mission_id(p),
        brief=_brief(p, summary="Infiltrate and destroy the target structure.",
                     objectives=["Reach the target", "Plant charges", "Exfiltrate"],
                     tags=["stealth", "sabotage", "night"]),
        fsm=fsm,
        units=_player_squad(p, (50.0, 50.0, 0.0))
              + _enemy_group(p, (200.0, 200.0, 0.0), count=6),
    )


def _csar(p: dict) -> MissionBlueprint:
    # The "pilot" is e1 in the demo (an enemy until the designer reassigns
    # them to civilian). Mission ends once players reach within 5m AND all
    # immediate enemies are eliminated.
    fsm = FsmGraph(
        initial="locate",
        on_enter_global=["A3B_pilot = e1"],
        states=[
            FsmState(id="locate", label="Locate pilot",
                     transitions=[FsmTransition(
                         to="secure", kind=TransitionKind.TRIGGER,
                         condition="(player distance A3B_pilot) < 50",
                     )]),
            FsmState(id="secure", label="Secure LZ",
                     transitions=[FsmTransition(
                         to="win", kind=TransitionKind.TRIGGER,
                         condition='({alive _x && {side _x == east}} count allUnits) <= 1',
                     )]),
            FsmState(id="win", label="Pilot recovered", is_terminal=True, end_type="end1"),
        ],
    )
    return MissionBlueprint(
        mission_id=_mission_id(p),
        brief=_brief(p, summary="Recover the downed pilot.",
                     objectives=["Find the pilot", "Defend the LZ", "Extract"],
                     tags=["csar", "rescue"]),
        fsm=fsm,
        units=_player_squad(p, (300.0, 300.0, 0.0))
              + _enemy_group(p, (350.0, 360.0, 0.0), count=5),
    )


def _hvt(p: dict) -> MissionBlueprint:
    fsm = FsmGraph(
        initial="approach",
        on_enter_global=["A3B_hvt = e1"],
        states=[
            FsmState(id="approach", label="Approach compound",
                     transitions=[FsmTransition(
                         to="capture", kind=TransitionKind.TRIGGER,
                         condition="(player distance A3B_hvt) < 30",
                     )]),
            FsmState(id="capture", label="Capture HVT",
                     transitions=[FsmTransition(
                         to="win", kind=TransitionKind.TRIGGER,
                         condition="!alive A3B_hvt || {captive A3B_hvt}",
                     )]),
            FsmState(id="win", label="HVT captured", is_terminal=True, end_type="end1"),
        ],
    )
    return MissionBlueprint(
        mission_id=_mission_id(p),
        brief=_brief(p, summary="Capture the high-value target alive.",
                     objectives=["Reach the compound", "Capture HVT"],
                     tags=["hvt", "capture"]),
        fsm=fsm,
        units=_player_squad(p, (400.0, 400.0, 0.0))
              + _enemy_group(p, (450.0, 450.0, 0.0), count=7),
    )


def _recon(p: dict) -> MissionBlueprint:
    fsm = FsmGraph(
        initial="insert",
        on_enter_global=[
            "A3B_target = e1",
            "A3B_lzPos = position p1",
        ],
        states=[
            FsmState(id="insert", label="Insert",
                     transitions=[FsmTransition(
                         to="observe", kind=TransitionKind.TIMER, condition="30",
                     )]),
            FsmState(id="observe", label="Observe & report",
                     transitions=[FsmTransition(
                         to="exfil", kind=TransitionKind.TRIGGER,
                         condition="(player distance A3B_target) < 200 && {alive A3B_target}",
                     )]),
            FsmState(id="exfil", label="Exfiltrate",
                     transitions=[FsmTransition(
                         to="win", kind=TransitionKind.TRIGGER,
                         condition="(player distance A3B_lzPos) > 600",
                     )]),
            FsmState(id="win", label="Intel delivered", is_terminal=True, end_type="end1"),
        ],
    )
    return MissionBlueprint(
        mission_id=_mission_id(p),
        brief=_brief(p, summary="Conduct long-range reconnaissance.",
                     objectives=["Insert quietly", "Observe target", "Exfiltrate"],
                     tags=["recon", "stealth"]),
        fsm=fsm,
        units=_player_squad(p, (700.0, 700.0, 0.0))
              + _enemy_group(p, (720.0, 720.0, 0.0), count=4),
    )


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


_TEMPLATES: dict[str, MissionTemplate] = {
    t.id: t for t in [
        MissionTemplate(
            id="convoy", label="Convoy Escort",
            summary="Escort a convoy through a potential ambush corridor.",
            tags=["combat", "escort"],
            parameters=_COMMON_PARAMS, factory=_convoy,
        ),
        MissionTemplate(
            id="defend", label="Defend Position",
            summary="Hold a fixed point against repeated attacks.",
            tags=["combat", "defence"],
            parameters=_COMMON_PARAMS, factory=_defend,
        ),
        MissionTemplate(
            id="sabotage", label="Sabotage",
            summary="Infiltrate a hostile site and plant charges on a target.",
            tags=["stealth", "demolitions"],
            parameters=_COMMON_PARAMS, factory=_sabotage,
        ),
        MissionTemplate(
            id="csar", label="Combat Search & Rescue",
            summary="Locate and recover a downed friendly.",
            tags=["rescue"],
            parameters=_COMMON_PARAMS, factory=_csar,
        ),
        MissionTemplate(
            id="hvt", label="HVT Capture",
            summary="Capture a high-value target alive.",
            tags=["capture"],
            parameters=_COMMON_PARAMS, factory=_hvt,
        ),
        MissionTemplate(
            id="recon", label="Reconnaissance",
            summary="Covertly observe and report on enemy activity.",
            tags=["stealth", "intel"],
            parameters=_COMMON_PARAMS, factory=_recon,
        ),
    ]
}


def list_templates() -> list[MissionTemplate]:
    return list(_TEMPLATES.values())


def get_template(template_id: str) -> MissionTemplate:
    if template_id not in _TEMPLATES:
        raise KeyError(f"Unknown template '{template_id}'")
    return _TEMPLATES[template_id]
