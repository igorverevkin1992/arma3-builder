"""Shared pytest fixtures."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Force the stub LLM provider during tests so we never call out.
os.environ.setdefault("ARMA3_LLM_PROVIDER", "stub")
os.environ.setdefault("ARMA3_RAG_BACKEND", "memory")

from arma3_builder.arma.classnames import ClassnameInfo, ClassnameRegistry  # noqa: E402
from arma3_builder.protocols import (  # noqa: E402
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


@pytest.fixture()
def registry() -> ClassnameRegistry:
    reg = ClassnameRegistry.from_seed_files(ROOT / "data" / "seed_classnames")
    if not reg.items:
        reg.register(ClassnameInfo(
            classname="B_Soldier_F", addon="A3_Characters_F",
            type="Man", faction="BLU_F", side="WEST",
        ))
        reg.register(ClassnameInfo(
            classname="O_Soldier_F", addon="A3_Characters_F",
            type="Man", faction="OPF_F", side="EAST",
        ))
    return reg


@pytest.fixture()
def mission_blueprint() -> MissionBlueprint:
    fsm = FsmGraph(
        initial="start",
        states=[
            FsmState(
                id="start",
                label="Start",
                transitions=[FsmTransition(to="end", kind=TransitionKind.TRIGGER, condition="true")],
            ),
            FsmState(
                id="end",
                label="End",
                is_terminal=True,
                end_type="end1",
            ),
        ],
    )
    return MissionBlueprint(
        brief=MissionBrief(
            title="Test Mission",
            summary="A test mission",
            map="VR",
            side="WEST",
            enemy_side="EAST",
            objectives=["Reach the LZ"],
            time_of_day="06:00",
            weather="clear",
            player_count=2,
        ),
        fsm=fsm,
        units=[
            UnitPlacement(
                classname="B_Soldier_F",
                side="WEST",
                position=(100.0, 100.0, 0.0),
                is_player=True,
                is_leader=True,
                group_id="player",
            ),
            UnitPlacement(
                classname="O_Soldier_F",
                side="EAST",
                position=(200.0, 200.0, 0.0),
                group_id="enemy",
            ),
        ],
        waypoints=[Waypoint(group_id="enemy", position=(150.0, 150.0, 0.0))],
        diary=Diary(
            entries=[BriefingEntry(tab="Situation", title="Situation", text="Test situation")],
            tasks=[{"id": "task1", "title": "T", "description": "Reach the LZ"}],
        ),
        addons=["A3_Characters_F"],
    )


@pytest.fixture()
def campaign_brief() -> CampaignBrief:
    return CampaignBrief(
        name="Test Campaign",
        author="tester",
        overview="A campaign for testing",
        mods=["cba_main"],
        factions={"WEST": "BLU_F", "EAST": "OPF_F"},
        missions=[
            MissionBrief(
                title="Mission One",
                summary="Test",
                map="VR",
                side="WEST",
                enemy_side="EAST",
                objectives=["Win"],
            ),
        ],
    )


@pytest.fixture()
def campaign_plan(campaign_brief, mission_blueprint) -> CampaignPlan:
    return CampaignPlan(brief=campaign_brief, blueprints=[mission_blueprint])
