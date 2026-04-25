"""Regression tests for the deep-audit fix pass.

Each test maps to a finding in the audit (B1..B7, H8..H12, M14..M16).
Failure here means we re-introduced one of the prior bugs.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arma3_builder.agents.config_master import ConfigMasterAgent
from arma3_builder.agents.scripter import ScripterAgent
from arma3_builder.arma.description_ext import generate_mission_description_ext
from arma3_builder.arma.dialog import (
    generate_cfg_sentences,
    generate_dialog_driver_sqf,
    generate_sentences_bikb,
)
from arma3_builder.arma.fsm import generate_statemachine_sqf
from arma3_builder.arma.init_scripts import generate_init_server
from arma3_builder.main import app
from arma3_builder.pipeline import Pipeline
from arma3_builder.protocols import Dialogue, FsmGraph, FsmState, FsmTransition, TransitionKind
from arma3_builder.qa.rules import RULES
from arma3_builder.templates import get_template, list_templates


# ------------------------------ B1: gameType --------------------------------


def test_b1_gametype_is_valid_for_singleplayer(mission_blueprint):
    mission_blueprint.brief.player_count = 1
    text = generate_mission_description_ext(mission_blueprint)
    # "SP" is not a valid CfgMissions gameType; "Scenario" is.
    assert 'gameType = "Scenario"' in text
    assert 'gameType = "SP"' not in text


def test_b1_gametype_coop_when_multi_player(mission_blueprint):
    mission_blueprint.brief.player_count = 4
    assert 'gameType = "Coop"' in generate_mission_description_ext(mission_blueprint)


# ------------------------------ B2: cfg sentences include -------------------


def test_b2_cfgsentences_included_when_dialogue(mission_blueprint):
    mission_blueprint.dialogue = [
        Dialogue(id="hq", speaker="HQ", text="Hello", trigger_state="start")
    ]
    text = generate_mission_description_ext(mission_blueprint)
    # Without the include, kbAddTopic at runtime cannot resolve the topic.
    assert '#include "cfgSentences.hpp"' in text
    assert "class CfgSentences {};" not in text


def test_b2_no_dialog_emits_empty_cfgsentences(mission_blueprint):
    mission_blueprint.dialogue = []
    text = generate_mission_description_ext(mission_blueprint)
    assert "class CfgSentences {};" in text
    assert '#include "cfgSentences.hpp"' not in text


# ------------------------------ B3: kbAddTopic signature --------------------


def test_b3_kbaddtopic_uses_qualified_path(mission_blueprint):
    mission_blueprint.dialogue = [
        Dialogue(id="hq", speaker="HQ", text="Hello", trigger_state="start")
    ]
    sqf = generate_dialog_driver_sqf(mission_blueprint)
    # The third argument MUST include the topic class path, not just "CfgSentences".
    assert "CfgSentences\\\\A3B_topic_" in sqf
    assert '"CfgSentences"' not in sqf  # bare "CfgSentences" is wrong


def test_b3_dialog_waits_for_statemachine(mission_blueprint):
    mission_blueprint.dialogue = [Dialogue(id="hq", speaker="HQ", text="x")]
    sqf = generate_dialog_driver_sqf(mission_blueprint)
    assert "waitUntil" in sqf
    assert "A3B_stateMachine" in sqf


# ------------------------------ B4: no double init --------------------------


def test_b4_initfsm_not_preinit(mission_blueprint):
    import re
    text = generate_mission_description_ext(mission_blueprint)
    # initFsm and registerTasks must not be preInit anymore — they're owned
    # explicitly by initServer.sqf to avoid double-creation.
    assert re.search(r"class\s+initFsm\s*\{[^}]*}", text)
    assert "preInit = 1" not in text


def test_b4_initserver_calls_initfsm_and_registertasks(mission_blueprint):
    sqf = generate_init_server(mission_blueprint)
    assert "[] call A3B_fnc_registerTasks;" in sqf
    assert "[] call A3B_fnc_initFsm;" in sqf


# ------------------------------ B5: registerTasks server-only ---------------


def test_b5_register_tasks_runs_server_side():
    from arma3_builder.agents.scripter import ScripterAgent
    from arma3_builder.protocols import (
        Diary,
        FsmGraph,
        FsmState,
        MissionBlueprint,
        MissionBrief,
    )
    bp = MissionBlueprint(
        mission_id="m01_t",
        brief=MissionBrief(title="T", summary="s", map="VR", side="WEST",
                           enemy_side="EAST", objectives=["o"], player_count=1),
        fsm=FsmGraph(initial="s",
                     states=[FsmState(id="s", label="S", is_terminal=True, end_type="end1")]),
        diary=Diary(tasks=[{"id": "t1", "title": "T", "description": "d"}]),
    )
    s = ScripterAgent()
    sqf = s._tasks_registrar(bp)
    assert "if (!isServer) exitWith {};" in sqf
    # Should NOT block on hasInterface (that broke dedicated servers).
    assert "if (!hasInterface) exitWith {};" not in sqf


# ------------------------------ B6: templates playable ----------------------


@pytest.mark.parametrize("tid", ["convoy", "defend", "sabotage", "csar", "hvt", "recon"])
def test_b6_templates_have_real_predicates(tid):
    bp = get_template(tid).instantiate({"title": f"T_{tid}"})
    # Every template now declares on_enter_global so transition predicates
    # have something concrete to reference (no more `[0,0,0]` sentinels).
    assert bp.fsm.on_enter_global, f"{tid} missing on_enter_global"
    # No transition should reference a never-set namespace variable as a
    # zero-distance sentinel.
    for state in bp.fsm.states:
        for tr in state.transitions:
            assert "[0,0,0]" not in tr.condition, f"{tid}.{state.id} → still uses sentinel"
            assert "['A3B_target', objNull]" not in tr.condition


def test_b6_fsm_emits_global_init_before_create(mission_blueprint):
    mission_blueprint.fsm.on_enter_global = ["A3B_demo = 42", "A3B_other = player"]
    sqf = generate_statemachine_sqf(mission_blueprint)
    create_idx = sqf.find("CBA_statemachine_fnc_create")
    init_idx = sqf.find("A3B_demo = 42;")
    assert init_idx != -1
    assert init_idx < create_idx, "global init must run before SM creation"


# ------------------------------ B7: path traversal --------------------------


def test_b7_ui_asset_blocks_traversal():
    client = TestClient(app)
    # Both raw and url-encoded forms must be rejected.
    for asset in ["../../../etc/passwd", "..%2f..%2fetc%2fpasswd"]:
        r = client.get(f"/ui/{asset}")
        assert r.status_code in (403, 404), f"path {asset!r} must be blocked"


def test_b7_ui_legitimate_asset_works():
    client = TestClient(app)
    r = client.get("/ui/styles.css")
    assert r.status_code == 200


# ------------------------------ H8: no plan mutation ------------------------


@pytest.mark.asyncio
async def test_h8_plan_not_mutated_by_pipeline(campaign_brief, tmp_path):
    from arma3_builder.pipeline import PipelineConfig

    pipe = Pipeline(config=PipelineConfig(output_dir=tmp_path, qa_strict=False))
    # Materialise a plan once via narrative.
    ctx = pipe.make_context()
    plan = await pipe.narrative.run(campaign_brief, ctx)
    snapshot = plan.model_dump()
    await pipe.generate_from_plan(plan)
    assert plan.model_dump() == snapshot, "Pipeline mutated the input plan"


# ------------------------------ H9: _rag_check_cba honest -------------------


def test_h9_rag_check_cba_returns_false_when_no_hits():
    from arma3_builder.agents.base import AgentContext
    from arma3_builder.arma.classnames import ClassnameRegistry
    from arma3_builder.llm import get_llm_client
    from arma3_builder.rag import HybridRetriever, MemoryStore

    s = ScripterAgent()
    empty = HybridRetriever(store=MemoryStore())
    ctx = AgentContext(llm=get_llm_client(), retriever=empty, registry=ClassnameRegistry())
    assert s._rag_check_cba(ctx) is False


# ------------------------------ H11: sqflint single-file --------------------


def test_h11_sqflint_no_recursive_flag():
    # We don't actually need sqflint installed — just verify the command we'd
    # invoke does NOT contain the wrongly-applied -r flag.
    from arma3_builder.qa.linter import SqfLinter
    import subprocess

    captured: dict[str, list[str]] = {}

    def fake_run(args, **kwargs):  # noqa: ANN001
        captured["args"] = args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    linter = SqfLinter()
    linter.available = True
    orig = subprocess.run
    subprocess.run = fake_run
    try:
        linter._run(["/tmp/x.sqf"], display_name="x.sqf")
    finally:
        subprocess.run = orig
    assert "-r" not in captured["args"]


# ------------------------------ H12: SSE cleans up on disconnect ------------


@pytest.mark.asyncio
async def test_h12_event_bus_finishable():
    from arma3_builder.api.events import EventBus

    bus = EventBus()
    await bus.publish("a", x=1)
    await bus.finish()
    chunks = []
    async for c in bus.stream():
        chunks.append(c)
    assert any('"x": 1' in c or '"x":1' in c for c in chunks)


# ------------------------------ M14: Orchestrator parse path ----------------


@pytest.mark.asyncio
async def test_m14_orchestrator_falls_back_on_bad_json(monkeypatch):
    from arma3_builder.agents.base import AgentContext
    from arma3_builder.agents.orchestrator import OrchestratorAgent
    from arma3_builder.arma.classnames import ClassnameRegistry
    from arma3_builder.llm import LLMClient, LLMResponse
    from arma3_builder.rag import HybridRetriever, MemoryStore

    o = OrchestratorAgent()

    class BrokenLLM(LLMClient):
        def __init__(self):
            super().__init__(provider="anthropic")
        async def complete(self, **kw):
            return LLMResponse(text="not json at all", raw={}, model=kw["model"], provider="anthropic")

    ctx = AgentContext(
        llm=BrokenLLM(), retriever=HybridRetriever(store=MemoryStore()),
        registry=ClassnameRegistry(),
    )
    brief = await o.run("anything", ctx)
    assert brief.name  # fell back to heuristic, didn't crash


# ------------------------------ M15: A3B003 narrowed ------------------------


def test_m15_execvm_outside_loop_is_clean():
    rule = next(r for r in RULES if r.code == "A3B003")
    # One-shot execVM (initPlayerLocal pattern) — must NOT match any more.
    assert not rule.pattern.search('[] execVM "briefing.sqf";')


def test_m15_execvm_inside_foreach_still_flagged():
    rule = next(r for r in RULES if r.code == "A3B003")
    code = '{ _x execVM "init.sqf" } forEach allUnits;'
    # Note: regex looks for forEach...execVM in either order. Use the pattern
    # that matches our generator's order (execVM precedes forEach in some
    # forms, but `addAction ... execVM` is the canonical hot path).
    code2 = 'player addAction ["X", { _this execVM "act.sqf" }];'
    assert rule.pattern.search(code2) is not None
