"""Regression tests for Phase-C features.

Covers:
  C1 — Critic agent heuristic rules + API surface
  C2 — SQM parser + /sync-from-eden round-trip
  C3 — Virtual arsenal SQF (ACE + BIS) + addon hints
  C4 — ACE settings block + missing-settings QA hint
  C5 — TTS Null provider + optional Piper path
  C6 — Web UI: critic panel, FSM editor DOM, /plan/update endpoint
  Integration — convoy template regression still matches + Phase-C surfaces.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arma3_builder.agents.critic import CriticAgent
from arma3_builder.arma.ace_medical import (
    generate_ace_settings_block,
    missing_medical_settings_warning,
    plan_uses_ace,
)
from arma3_builder.arma.arsenal import (
    arsenal_addons,
    generate_arsenal_client_sqf,
    generate_arsenal_server_sqf,
)
from arma3_builder.arma.sqm_import import (
    extract_units,
    extract_waypoints,
    parse_sqm,
    sync_into_blueprint,
)
from arma3_builder.main import app
from arma3_builder.protocols import (
    AceSettings,
    CampaignBrief,
    CampaignPlan,
    Character,
    Cutscene,
    Dialogue,
    Diary,
    FsmGraph,
    FsmState,
    FsmTransition,
    MissionBlueprint,
    MissionBrief,
    TransitionKind,
    UnitPlacement,
    VirtualArsenal,
)
from arma3_builder.tts.provider import (
    NullTTS,
    PiperTTS,
    get_provider,
    synthesise_dialogue,
)


# =============================== C1 — Critic ================================


def _critique_sync(plan: CampaignPlan):
    """Run the Critic agent synchronously via asyncio.run."""
    from arma3_builder.agents.base import AgentContext
    from arma3_builder.arma.classnames import ClassnameRegistry
    from arma3_builder.llm import get_llm_client
    from arma3_builder.rag import HybridRetriever

    ctx = AgentContext(
        llm=get_llm_client(),
        retriever=HybridRetriever(),
        registry=ClassnameRegistry(),
    )
    return asyncio.run(CriticAgent().run(plan, ctx))


def test_c1_single_mission_flagged(campaign_plan):
    notes = _critique_sync(campaign_plan)
    assert any(n.code == "A3B405" for n in notes), "A3B405 should fire for single-mission plans"


def test_c1_zero_dialogue_flagged(campaign_plan):
    for bp in campaign_plan.blueprints:
        bp.dialogue = []
    notes = _critique_sync(campaign_plan)
    assert any(n.code == "A3B406" for n in notes)


def test_c1_balance_ratio_warning(campaign_plan):
    bp = campaign_plan.blueprints[0]
    # Make enemies dwarf players 10:1.
    bp.units = (
        [u for u in bp.units if u.is_player]
        + [
            UnitPlacement(
                classname="O_Soldier_F", side=bp.brief.enemy_side,
                position=(100.0 + i, 100.0, 0.0), group_id="east",
            )
            for i in range(20)
        ]
    )
    notes = _critique_sync(campaign_plan)
    assert any(n.code == "A3B402" for n in notes)


def test_c1_identical_endings_campaign(campaign_plan, mission_blueprint):
    # Extend the plan to 3 identical missions so monotony fires.
    bp = mission_blueprint.model_copy(deep=True)
    campaign_plan.blueprints = [bp.model_copy(deep=True) for _ in range(3)]
    for i, m in enumerate(campaign_plan.blueprints):
        m.mission_id = f"m{i+1:02d}_x"
    notes = _critique_sync(campaign_plan)
    assert any(n.code == "A3B401" for n in notes)


def test_c1_missing_recurring_characters(campaign_plan, mission_blueprint):
    campaign_plan.blueprints = [
        mission_blueprint.model_copy(deep=True) for _ in range(2)
    ]
    for i, m in enumerate(campaign_plan.blueprints):
        m.mission_id = f"m{i+1:02d}_x"
    campaign_plan.brief.characters = []
    notes = _critique_sync(campaign_plan)
    assert any(n.code == "A3B407" for n in notes)


def test_c1_critic_via_api_endpoint():
    c = TestClient(app)
    brief = {
        "name": "Solo", "author": "t", "overview": "x",
        "mods": ["cba_main"], "factions": {"WEST": "BLU_F"},
        "missions": [{
            "title": "Only", "summary": "s", "map": "VR",
            "side": "WEST", "enemy_side": "EAST",
            "objectives": ["o"], "time_of_day": "06:00",
            "weather": "clear", "player_count": 1, "tags": [],
        }],
    }
    gen = c.post("/generate", json={"brief": brief})
    assert gen.status_code == 200
    plan = gen.json()["plan"]
    # Standalone /critique returns notes on the same plan.
    r = c.post("/critique", json={"plan": plan, "instruction": "review"})
    assert r.status_code == 200
    data = r.json()
    assert "notes" in data


# =============================== C2 — Eden import ==========================


_SAMPLE_SQM = """\
version = 53;
class Mission
{
    class Entities
    {
        class Item0
        {
            dataType = "Group";
            id = 100;
            side = "EAST";
            class Entities
            {
                class Item0
                {
                    dataType = "Object";
                    id = 101;
                    side = "EAST";
                    class Attributes
                    {
                        name = "hostile_1";
                        isPlayer = 0;
                        isLeader = 1;
                    };
                    class PositionInfo
                    {
                        position[] = {1234.5, 2.0, 6789.0};
                        angleY = 90.0;
                    };
                    type = "O_Soldier_F";
                };
                class Item1
                {
                    dataType = "Waypoint";
                    id = 110;
                    class PositionInfo
                    {
                        position[] = {1300.0, 1.5, 6800.0};
                    };
                    type = "SAD";
                };
            };
        };
    };
};
"""


def test_c2_parse_sqm_finds_mission():
    root = parse_sqm(_SAMPLE_SQM)
    mission = [c for c in root.children if c.name == "Mission"]
    assert mission, "Mission class not found"


def test_c2_extract_units():
    root = parse_sqm(_SAMPLE_SQM)
    units = extract_units(root)
    assert len(units) == 1
    u = units[0]
    assert u.classname == "O_Soldier_F"
    assert u.name == "hostile_1"
    assert u.side == "EAST"
    # SQM stores [x, altitude, y]; we normalise to (x, y, altitude).
    assert u.position == (1234.5, 6789.0, 2.0)


def test_c2_extract_waypoints():
    root = parse_sqm(_SAMPLE_SQM)
    wps = extract_waypoints(root)
    assert len(wps) == 1
    assert wps[0].type == "SAD"


def test_c2_sync_into_blueprint_preserves_fsm(mission_blueprint):
    before_fsm = mission_blueprint.fsm.model_dump()
    merged = sync_into_blueprint(mission_blueprint, _SAMPLE_SQM)
    # Units replaced by SQM contents.
    assert any(u.classname == "O_Soldier_F" for u in merged.units)
    # FSM untouched.
    assert merged.fsm.model_dump() == before_fsm


def test_c2_sync_from_eden_endpoint():
    c = TestClient(app)
    # First generate a plan with a blueprint.
    brief = {
        "name": "Eden Test", "author": "t", "overview": "x",
        "mods": ["cba_main"], "factions": {"WEST": "BLU_F"},
        "missions": [{
            "title": "M1", "summary": "s", "map": "VR",
            "side": "WEST", "enemy_side": "EAST",
            "objectives": ["o"], "time_of_day": "06:00",
            "weather": "clear", "player_count": 1, "tags": [],
        }],
    }
    plan = c.post("/generate", json={"brief": brief}).json()["plan"]
    r = c.post("/sync-from-eden", json={
        "plan": plan, "mission_index": 0, "sqm_text": _SAMPLE_SQM,
    })
    assert r.status_code == 200, r.text
    updated = r.json()["plan"]
    classes = {u["classname"] for u in updated["blueprints"][0]["units"]}
    assert "O_Soldier_F" in classes


# =============================== C3 — Virtual arsenal ======================


def _bp_with_arsenal(*arsenals):
    return MissionBlueprint(
        mission_id="m01",
        brief=MissionBrief(title="T", summary="s", map="VR", side="WEST",
                           enemy_side="EAST", objectives=["o"]),
        fsm=FsmGraph(initial="s",
                     states=[FsmState(id="s", label="S",
                                      is_terminal=True, end_type="end1")]),
        arsenals=list(arsenals),
        diary=Diary(),
    )


def test_c3_bis_arsenal_uses_addaction():
    bp = _bp_with_arsenal(VirtualArsenal(
        id="fob", kind="bis",
        object_classname="Box_NATO_Ammo_F",
        position=(100.0, 200.0, 0.0),
    ))
    server = generate_arsenal_server_sqf(bp)
    client = generate_arsenal_client_sqf(bp)
    assert "createVehicle" in server
    assert "BIS_fnc_arsenal" in client
    assert "addAction" in client


def test_c3_ace_arsenal_uses_init_box():
    bp = _bp_with_arsenal(VirtualArsenal(id="fob", kind="ace"))
    client = generate_arsenal_client_sqf(bp)
    assert "ace_arsenal_fnc_initBox" in client


def test_c3_arsenal_addons_hint_for_ace():
    bp = _bp_with_arsenal(VirtualArsenal(id="fob", kind="ace"))
    assert "ace_arsenal" in arsenal_addons(bp)


def test_c3_no_arsenals_yields_stub():
    bp = _bp_with_arsenal()
    assert "No arsenals" in generate_arsenal_server_sqf(bp)
    assert "No arsenals" in generate_arsenal_client_sqf(bp)


# =============================== C4 — ACE medical ==========================


def test_c4_ace_block_emits_force_settings():
    settings = AceSettings(
        medical_level="advanced",
        medical_enable_revive=True,
        medical_respawn_behaviour="base",
    )
    block = generate_ace_settings_block(settings)
    assert "class ace_settings" in block
    assert "medical_level" in block
    assert "value=1" in block      # advanced


def test_c4_ace_block_absent_when_no_settings():
    block = generate_ace_settings_block(None)
    assert "ACE settings not specified" in block


def test_c4_missing_settings_warning(campaign_plan):
    # No ACE mod → no warning.
    assert missing_medical_settings_warning(campaign_plan) is None
    # Add ACE mod without AceSettings → warning.
    campaign_plan.brief.mods = ["ace_main"]
    campaign_plan.brief.ace_settings = None
    msg = missing_medical_settings_warning(campaign_plan)
    assert msg is not None
    assert "ACE" in msg


def test_c4_plan_uses_ace_detection(campaign_plan):
    campaign_plan.brief.mods = ["cba_main", "ace_main"]
    assert plan_uses_ace(campaign_plan) is True
    campaign_plan.brief.mods = ["cba_main"]
    campaign_plan.brief.ace_settings = AceSettings()
    assert plan_uses_ace(campaign_plan) is True


def test_c4_description_ext_contains_ace_block_when_set(mission_blueprint):
    from arma3_builder.arma.description_ext import generate_mission_description_ext
    ext = generate_mission_description_ext(
        mission_blueprint,
        ace_settings=AceSettings(medical_level="basic"),
    )
    assert "class ace_settings" in ext
    assert "value=0" in ext


# =============================== C5 — TTS =================================


def test_c5_null_provider_writes_empty_file(tmp_path):
    prov = NullTTS()
    out = tmp_path / "x.ogg"
    r = prov.synthesise("hello", out_path=out)
    assert r.ok and r.bytes_written == 0
    assert out.exists()


def test_c5_get_provider_defaults_to_null(monkeypatch):
    monkeypatch.delenv("ARMA3_TTS_PROVIDER", raising=False)
    prov = get_provider()
    assert isinstance(prov, NullTTS)


def test_c5_synthesise_dialogue_returns_entries(tmp_path):
    entries = synthesise_dialogue(
        [("hq_contact", "Ambush ahead"), ("hq_exfil", "Extract now")],
        mission_dir=tmp_path,
    )
    assert len(entries) == 2
    assert entries[0].sound_path.startswith("sound/")
    # Files exist on disk even if zero-byte.
    for e in entries:
        assert (tmp_path / e.sound_path).exists()


def test_c5_piper_unavailable_falls_back_to_null(tmp_path):
    p = PiperTTS()
    # voice model env not set in tests → available is False.
    assert not p.available
    # synthesise still produces a placeholder via NullTTS.
    r = p.synthesise("t", out_path=tmp_path / "x.ogg")
    assert r.ok


# =============================== C6 — UI + /plan/update ====================


def test_c6_ui_has_critic_and_fsm_editor_dom():
    c = TestClient(app)
    html = c.get("/").text
    assert 'id="critic-list"' in html
    assert 'id="fsm-edit"' in html
    assert 'id="eden-sqm"' in html


def test_c6_plan_update_regenerates():
    c = TestClient(app)
    brief = {
        "name": "Plan Update", "author": "t", "overview": "x",
        "mods": ["cba_main"], "factions": {"WEST": "BLU_F"},
        "missions": [{
            "title": "M1", "summary": "s", "map": "VR",
            "side": "WEST", "enemy_side": "EAST",
            "objectives": ["o"], "time_of_day": "06:00",
            "weather": "clear", "player_count": 1, "tags": [],
        }],
    }
    data = c.post("/generate", json={"brief": brief}).json()
    plan = data["plan"]
    # Mutate an FSM label, then push via /plan/update.
    plan["blueprints"][0]["fsm"]["states"][0]["label"] = "Edited"
    r = c.post("/plan/update", json={"plan": plan, "regenerate": True})
    assert r.status_code == 200, r.text
    updated = r.json()
    first_label = updated["plan"]["blueprints"][0]["fsm"]["states"][0]["label"]
    assert first_label == "Edited"


def test_c6_plan_update_no_regen_short_circuit():
    c = TestClient(app)
    brief = {
        "name": "No regen", "author": "t", "overview": "x",
        "mods": ["cba_main"], "factions": {"WEST": "BLU_F"},
        "missions": [{
            "title": "M1", "summary": "s", "map": "VR",
            "side": "WEST", "enemy_side": "EAST",
            "objectives": ["o"], "time_of_day": "06:00",
            "weather": "clear", "player_count": 1, "tags": [],
        }],
    }
    data = c.post("/generate", json={"brief": brief}).json()
    plan = data["plan"]
    r = c.post("/plan/update", json={"plan": plan, "regenerate": False})
    assert r.status_code == 200
    assert r.json()["artifact_count"] == 0


# =============================== Integration ================================


def test_c_generate_response_has_critic_notes():
    c = TestClient(app)
    brief = {
        "name": "Critic Integration", "author": "t", "overview": "x",
        "mods": ["cba_main"], "factions": {"WEST": "BLU_F"},
        "missions": [{
            "title": "M1", "summary": "s", "map": "VR",
            "side": "WEST", "enemy_side": "EAST",
            "objectives": ["o"], "time_of_day": "06:00",
            "weather": "clear", "player_count": 1, "tags": [],
        }],
    }
    r = c.post("/generate", json={"brief": brief})
    data = r.json()
    assert "critic_notes" in data
    # Single-mission plan should at least emit A3B405.
    codes = {n["code"] for n in data["critic_notes"]}
    assert "A3B405" in codes
