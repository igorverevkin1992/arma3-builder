"""Regression tests for Phase-A features.

Covers:
  A1 — pacing classifier and findings
  A2 — loadout catalogue and SQF emitter
  A3 — support-asset SQF
  A4 — playtester reachability / liveness / condition sanity
  A5 — LLM usage/cost accumulation
  A6 — wizard UI endpoints
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arma3_builder.arma.loadout import (
    generate_loadout_sqf,
    generate_loadout_hook_sqf,
    lobby_param_block,
    resolve_loadouts,
)
from arma3_builder.arma.support import (
    generate_support_actions_sqf,
    generate_support_sqf,
)
from arma3_builder.llm.usage import (
    UsageAccumulator,
    UsageEvent,
    estimate_cost,
    estimate_tokens_from_text,
)
from arma3_builder.main import app
from arma3_builder.protocols import (
    FsmGraph,
    FsmState,
    FsmTransition,
    MissionBlueprint,
    StateKind,
    SupportAsset,
    TransitionKind,
)
from arma3_builder.qa.pacing import (
    MissionPacing,
    analyse_campaign,
    analyse_mission,
    classify_state,
    estimate_duration,
)
from arma3_builder.qa.playtester import playtest_campaign, playtest_mission


# ============================== A1 — Pacing ================================


def test_a1_classifier_infers_engagement_from_label():
    st = FsmState(id="s", label="Ambush corridor")
    assert classify_state(st) == StateKind.ENGAGEMENT


def test_a1_classifier_respects_explicit_kind():
    st = FsmState(id="s", label="Random", kind=StateKind.STEALTH)
    assert classify_state(st) == StateKind.STEALTH


def test_a1_duration_prefers_timer_transitions():
    st = FsmState(
        id="s", label="Prepare",
        transitions=[FsmTransition(to="next", kind=TransitionKind.TIMER,
                                   condition="120")],
    )
    # Timer takes precedence over kind default.
    assert estimate_duration(st) == 120


def test_a1_empty_engagement_flags_a3b310(campaign_plan):
    for bp in campaign_plan.blueprints:
        bp.fsm = FsmGraph(
            initial="s0",
            states=[
                # Long dialogue-only state (>= 120s) so A3B310 fires.
                FsmState(id="s0", label="Talk",
                         kind=StateKind.DIALOGUE, expected_seconds=180,
                         transitions=[FsmTransition(to="end1",
                             kind=TransitionKind.TRIGGER, condition="true")]),
                FsmState(id="end1", label="End",
                         is_terminal=True, end_type="end1"),
            ],
        )
    report = analyse_campaign(campaign_plan)
    codes = {f.code for f in report.findings}
    assert "A3B310" in codes


def test_a1_mission_timeline_is_non_empty(campaign_plan):
    report = analyse_campaign(campaign_plan)
    for m in report.missions:
        assert m.timeline, f"{m.mission_id} timeline is empty"
        assert all(s.seconds > 0 for s in m.timeline[:-1])


# ============================== A2 — Loadout ================================


def test_a2_resolve_loadouts_falls_back_to_vanilla():
    kits = resolve_loadouts(None, faction_hint="unknown_faction")
    # vanilla has 6 roles; we requested default 4-role set
    assert 1 <= len(kits) <= 6
    for k in kits:
        assert k.role_id
        assert k.uniform or k.vest  # baseline gear present


def test_a2_resolve_loadouts_mixes_rhs_and_vanilla():
    kits = resolve_loadouts(None, faction_hint="rhsusf_main")
    names = {k.role_id for k in kits}
    # autorifleman has no rhsusf_main override → falls back to vanilla kit,
    # but role_id is still populated.
    assert {"team_leader", "rifleman", "medic"}.issubset(names)


def test_a2_sqf_emitter_contains_case_per_role():
    kits = resolve_loadouts(None, faction_hint="vanilla")
    sqf = generate_loadout_sqf(kits)
    for kit in kits:
        assert f'case "{kit.role_id}"' in sqf
    assert "removeAllWeapons _u;" in sqf
    assert "default {" in sqf


def test_a2_lobby_params_has_role_picker():
    kits = resolve_loadouts(None, faction_hint="vanilla")
    text = lobby_param_block(kits)
    assert "class Params" in text
    assert "class A3B_role" in text
    assert 'title = "Starting role"' in text


def test_a2_hook_reads_role_variable():
    assert 'getVariable ["A3B_role_override"' in generate_loadout_hook_sqf()


def test_a2_no_loadouts_yields_stub(mission_blueprint):
    assert "vanilla starting gear is preserved" in generate_loadout_sqf([])


# ============================== A3 — Support ================================


def _bp_with_support(*assets):
    from arma3_builder.protocols import (
        Diary, FsmGraph, FsmState, MissionBlueprint, MissionBrief,
    )
    return MissionBlueprint(
        mission_id="m01_t",
        brief=MissionBrief(
            title="T", summary="s", map="VR", side="WEST",
            enemy_side="EAST", objectives=["o"], player_count=2,
        ),
        fsm=FsmGraph(initial="s",
                     states=[FsmState(id="s", label="S",
                                      is_terminal=True, end_type="end1")]),
        support_assets=list(assets),
        diary=Diary(),
    )


def test_a3_cas_sqf_spawns_plane_and_ordnance():
    bp = _bp_with_support(SupportAsset(kind="cas", name="Wipeout run"))
    dispatcher = generate_support_sqf(bp)
    actions = generate_support_actions_sqf(bp)
    assert 'case "cas"' in dispatcher
    assert "createVehicle" in dispatcher
    # The actual classname is passed by the action handler as an argument;
    # the default filled in for "cas" lives in the register-actions file.
    assert "B_Plane_CAS_01_dynamicLoadout_F" in actions


def test_a3_artillery_sqf_creates_shells():
    bp = _bp_with_support(SupportAsset(kind="artillery", name="Fire mission"))
    dispatcher = generate_support_sqf(bp)
    actions = generate_support_actions_sqf(bp)
    assert 'case "artillery"' in dispatcher
    assert "Sh_82mm_AMOS" in actions


def test_a3_medevac_emits_helo_and_land():
    bp = _bp_with_support(SupportAsset(kind="medevac", name="Dust off"))
    sqf = generate_support_sqf(bp)
    assert 'case "medevac"' in sqf
    assert "land" in sqf.lower()


def test_a3_actions_register_action_with_cooldown():
    bp = _bp_with_support(SupportAsset(kind="cas", name="Wipeout", cooldown_seconds=300, uses=2))
    sqf = generate_support_actions_sqf(bp)
    assert "addAction" in sqf
    # Cooldown / use-count gating in the action body.
    assert "A3B_support_cas" in sqf
    assert 'remoteExec ["A3B_fnc_callSupport"' in sqf


def test_a3_empty_support_short_circuits():
    bp = _bp_with_support()
    assert "No support assets configured" in generate_support_sqf(bp)
    assert "No support actions" in generate_support_actions_sqf(bp)


# ============================== A4 — Playtester ============================


def _bp(fsm: FsmGraph, *, unit_names=("p1", "e1")) -> MissionBlueprint:
    from arma3_builder.protocols import (
        Diary, MissionBlueprint, MissionBrief, UnitPlacement,
    )
    units = []
    for i, name in enumerate(unit_names):
        units.append(UnitPlacement(
            classname="B_Soldier_F", side="WEST" if name.startswith("p") else "EAST",
            position=(float(i), float(i), 0.0), is_player=name.startswith("p"),
            group_id="g" + ("p" if name.startswith("p") else "e"),
            name=name,
        ))
    return MissionBlueprint(
        mission_id="m01_x",
        brief=MissionBrief(title="T", summary="s", map="VR", side="WEST",
                           enemy_side="EAST", objectives=["o"], player_count=1),
        fsm=fsm,
        units=units,
        diary=Diary(),
    )


def test_a4_unreachable_state_is_flagged():
    fsm = FsmGraph(
        initial="a",
        states=[
            FsmState(id="a", label="A",
                     transitions=[FsmTransition(to="end", kind=TransitionKind.TIMER, condition="5")]),
            FsmState(id="orphan", label="Orphan"),
            FsmState(id="end", label="End", is_terminal=True, end_type="end1"),
        ],
    )
    r = playtest_mission(_bp(fsm))
    codes = {f.code for f in r.findings}
    assert "A3B301" in codes


def test_a4_dead_end_is_flagged():
    fsm = FsmGraph(
        initial="a",
        states=[
            FsmState(id="a", label="A",
                     transitions=[FsmTransition(to="stuck", kind=TransitionKind.TRIGGER,
                                                condition="true")]),
            FsmState(id="stuck", label="Stuck"),  # no outgoing transitions, not terminal
        ],
    )
    r = playtest_mission(_bp(fsm))
    codes = {f.code for f in r.findings}
    assert "A3B302" in codes


def test_a4_undefined_variable_is_flagged():
    fsm = FsmGraph(
        initial="a",
        states=[
            FsmState(id="a", label="A",
                     transitions=[FsmTransition(
                         to="end", kind=TransitionKind.TRIGGER,
                         condition="A3B_nevertSet > 0",
                     )]),
            FsmState(id="end", label="End", is_terminal=True, end_type="end1"),
        ],
    )
    r = playtest_mission(_bp(fsm))
    codes = {f.code for f in r.findings}
    assert "A3B303" in codes


def test_a4_healthy_fsm_has_no_findings():
    fsm = FsmGraph(
        initial="a",
        on_enter_global=["A3B_target = e1"],
        states=[
            FsmState(id="a", label="A",
                     transitions=[FsmTransition(
                         to="end", kind=TransitionKind.TRIGGER,
                         condition="(player distance A3B_target) < 50",
                     )]),
            FsmState(id="end", label="End", is_terminal=True, end_type="end1"),
        ],
    )
    r = playtest_mission(_bp(fsm))
    assert r.findings == []


# ============================== A5 — Usage =================================


def test_a5_pricing_known_model():
    # gpt-4o: (0.005, 0.015) per 1k
    assert estimate_cost("gpt-4o", 1000, 0) == pytest.approx(0.005)
    assert estimate_cost("gpt-4o", 0, 1000) == pytest.approx(0.015)


def test_a5_pricing_unknown_model_is_zero():
    assert estimate_cost("nonexistent", 1_000_000, 1_000_000) == 0.0


def test_a5_accumulator_drain_resets_counter():
    acc = UsageAccumulator()
    acc.record(UsageEvent(
        provider="openai", model="gpt-4o", role="orchestrator",
        input_tokens=100, output_tokens=50, cost_usd=0.001, latency_ms=200,
    ))
    r = acc.drain()
    assert r.total_input_tokens == 100
    assert r.total_cost_usd == pytest.approx(0.001)
    # After drain, next snapshot should be empty.
    assert acc.snapshot().events == []


def test_a5_estimate_tokens_cheap():
    # 4 chars per token heuristic.
    assert estimate_tokens_from_text("abcd") == 1
    assert estimate_tokens_from_text("abcdefghij") == 2


# ============================== A6 — Wizard / API ==========================


def test_a6_ui_serves_wizard_markup():
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert "Wizard" in r.text
    assert "wizard-steps" in r.text


def test_a6_generate_response_includes_phase_a_fields():
    c = TestClient(app)
    payload = {
        "brief": {
            "name": "Phase A Test", "author": "t", "overview": "x",
            "mods": ["cba_main"], "factions": {"WEST": "BLU_F"},
            "missions": [{
                "title": "M1", "summary": "s", "map": "VR",
                "side": "WEST", "enemy_side": "EAST",
                "objectives": ["o"], "time_of_day": "06:00",
                "weather": "clear", "player_count": 1, "tags": [],
            }],
        }
    }
    r = c.post("/generate", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "pacing" in data and data["pacing"]
    assert "playtest" in data and isinstance(data["playtest"], list)
    assert "usage" in data and data["usage"] is not None
    # Score should now include an `overall` derived from pacing data too.
    assert "overall" in data["score"]


def test_a6_generate_includes_loadout_artifacts():
    c = TestClient(app)
    payload = {
        "brief": {
            "name": "Loadout Test", "author": "t", "overview": "x",
            "mods": ["cba_main"], "factions": {"WEST": "BLU_F"},
            "missions": [{
                "title": "Kit", "summary": "s", "map": "VR",
                "side": "WEST", "enemy_side": "EAST",
                "objectives": ["o"], "time_of_day": "06:00",
                "weather": "clear", "player_count": 4, "tags": [],
            }],
        }
    }
    r = c.post("/generate", json=payload)
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert plan["blueprints"]
    # Confirm the description.ext mission files reference applyLoadout.
    # We ask the filesystem since artifacts aren't returned in the response body.
    from pathlib import Path
    out = Path(r.json()["output_path"])
    assert (out / "missions").exists()
    ext = next((out / "missions").rglob("description.ext"))
    assert "class applyLoadout" in ext.read_text(encoding="utf-8")
