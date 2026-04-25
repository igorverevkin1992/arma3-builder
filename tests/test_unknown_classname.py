import pytest

from arma3_builder.agents.base import AgentContext
from arma3_builder.agents.config_master import ConfigMasterAgent
from arma3_builder.arma.classnames import ClassnameRegistry
from arma3_builder.llm import get_llm_client
from arma3_builder.protocols import (
    CampaignBrief,
    CampaignPlan,
    FsmGraph,
    FsmState,
    MissionBlueprint,
    MissionBrief,
    UnitPlacement,
)
from arma3_builder.qa.analyzer import validate_unknown_classnames
from arma3_builder.rag import HybridRetriever


@pytest.mark.asyncio
async def test_unknown_classname_flagged_by_qa():
    # Empty registry → any class will be unknown.
    registry = ClassnameRegistry()
    ctx = AgentContext(
        llm=get_llm_client(), retriever=HybridRetriever(),
        registry=registry,
    )

    bp = MissionBlueprint(
        mission_id="m01_t",
        brief=MissionBrief(
            title="T", summary="s", map="VR",
            side="WEST", enemy_side="EAST",
            objectives=["o"], player_count=1,
        ),
        fsm=FsmGraph(initial="s",
                     states=[FsmState(id="s", label="S", is_terminal=True, end_type="end1")]),
        units=[UnitPlacement(
            classname="nonexistent_rifleman",
            side="WEST", is_player=True, group_id="player",
            position=(0.0, 0.0, 0.0),
        )],
        addons=[],
    )
    plan = CampaignPlan(
        brief=CampaignBrief(name="C", overview="o", mods=[],
                            factions={"WEST": "BLU_F"}, missions=[bp.brief]),
        blueprints=[bp],
    )
    cm = ConfigMasterAgent()
    await cm.run(plan, ctx)
    unknowns = ctx.memory.get("unknown_classnames", [])
    assert "nonexistent_rifleman" in unknowns
    findings = validate_unknown_classnames(unknowns)
    assert any(f.code == "A3B210" for f in findings)
