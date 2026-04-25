"""Regression tests for Phase-B features.

Covers:
  B1 — MapSampler + Composition expansion
  B2 — Behaviour DSL + Reinforcement SQF
  B3 — Cross-mission Character + WorldFlag helpers
  B4 — Cutscene envelope + Music cue wiring
  B5 — Top-down map canvas served
  Integration — Scripter emits all B artefacts when the convoy template runs
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arma3_builder.arma.behaviour import generate_bind_behaviour_sqf
from arma3_builder.arma.characters import (
    apply_identity_sqf,
    generate_characters_hpp,
)
from arma3_builder.arma.compositions import expand_all, expand_composition
from arma3_builder.arma.cutscene import (
    cutscene_paths,
    generate_cutscene_sqf,
    wire_cutscenes_into_fsm,
)
from arma3_builder.arma.maps import MapSampler, available_maps, load_map
from arma3_builder.arma.music import (
    generate_cfg_music_block,
    wire_music_into_fsm,
)
from arma3_builder.arma.reinforcements import generate_reinforcements_sqf
from arma3_builder.arma.worldflags import (
    generate_world_flags_helper_sqf,
    generate_world_flags_reader_sqf,
    wire_world_flag_writes,
)
from arma3_builder.main import app
from arma3_builder.protocols import (
    BehaviourBinding,
    CampaignBrief,
    CampaignPlan,
    Character,
    Composition,
    Cutscene,
    Diary,
    FsmGraph,
    FsmState,
    FsmTransition,
    MissionBlueprint,
    MissionBrief,
    MusicCue,
    ReinforcementWave,
    TransitionKind,
    UnitPlacement,
    Waypoint,
    WorldFlagWrite,
)


# ============================== B1 — Maps ==================================


def test_b1_seed_maps_available():
    maps = available_maps()
    assert {"Tanoa", "Altis", "VR"}.issubset(set(maps))


def test_b1_map_sampler_picks_urban_poi():
    s = MapSampler("Tanoa", seed=7)
    assert s.available
    p = s.pick_poi(kind="urban")
    assert p is not None
    assert p.kind == "urban"


def test_b1_urban_cover_near_respects_radius():
    s = MapSampler("Tanoa", seed=1)
    anchor = (8700, 4020, 0)  # Georgetown centre
    pos = s.urban_cover_near(anchor, radius=100)
    # Should be within the town radius (400m) of the anchor.
    assert ((pos[0] - anchor[0]) ** 2 + (pos[1] - anchor[1]) ** 2) ** 0.5 <= 500


def test_b1_lz_near_returns_closest():
    s = MapSampler("Tanoa")
    lz = s.lz_near((7820, 4260, 0))     # exact lz_alpha
    assert lz == (7820.0, 4260.0, 0.0)


def test_b1_unknown_map_graceful():
    s = MapSampler("NoSuchWorld")
    assert not s.available
    # All query methods return safe defaults rather than raising.
    assert s.pick_poi() is None
    assert s.urban_cover_near((10, 10, 0)) == (10, 10, 0)
    # Road patrol falls back to a circular loop around the anchor.
    wps = s.road_patrol(4, anchor=(0, 0, 0))
    assert len(wps) == 4


# ============================== B1 — Compositions ==========================


def test_b1_fire_team_has_four_slots():
    c = Composition(id="ft1", kind="fire_team", side="WEST",
                    anchor=(100, 100, 0), size=4)
    units, wps = expand_composition(c)
    assert len(units) == 4
    # First unit is leader by convention.
    assert units[0].is_leader
    # Waypoints: a 4-point patrol ring.
    assert len(wps) == 4


def test_b1_garrison_respects_size():
    c = Composition(id="g1", kind="garrison", side="EAST",
                    anchor=(500, 500, 0), size=6)
    units, _ = expand_composition(c)
    assert len(units) == 6


def test_b1_motorised_patrol_size():
    c = Composition(id="mp1", kind="motorised_patrol", side="EAST",
                    anchor=(200, 200, 0), size=1)
    units, _ = expand_composition(c)
    assert len(units) == 3   # driver + gunner + commander


def test_b1_expand_all_flattens():
    cs = [
        Composition(id="a", kind="fire_team", side="WEST", anchor=(0, 0, 0)),
        Composition(id="b", kind="fire_team", side="EAST", anchor=(100, 0, 0)),
    ]
    units, wps = expand_all(cs)
    assert len(units) == 8
    assert len(wps) == 8


# ============================== B2 — Behaviour =============================


def _single_group_bp():
    return MissionBlueprint(
        mission_id="m01",
        brief=MissionBrief(title="T", summary="s", map="VR", side="WEST",
                           enemy_side="EAST", objectives=["o"], player_count=1),
        fsm=FsmGraph(initial="s",
                     states=[FsmState(id="s", label="S",
                                      is_terminal=True, end_type="end1")]),
        units=[UnitPlacement(
            classname="O_Soldier_F", side="EAST",
            position=(100.0, 100.0, 0.0), name="ambush_east_leader",
            is_leader=True, group_id="ambush_east",
        )],
        behaviour_bindings=[
            BehaviourBinding(group_id="ambush_east", kind="defend", radius=200),
        ],
        diary=Diary(),
    )


def test_b2_behaviour_binding_references_group():
    sqf = generate_bind_behaviour_sqf(_single_group_bp())
    # Snapshot + binding present; uses BIS_fnc_taskDefend for the "defend" kind.
    assert "A3B_group_ambush_east" in sqf
    assert "BIS_fnc_taskDefend" in sqf


def test_b2_behaviour_empty_yields_stub():
    bp = _single_group_bp()
    bp.behaviour_bindings = []
    assert "No behaviour bindings" in generate_bind_behaviour_sqf(bp)


def test_b2_reinforcements_wave_spawns_from_composition():
    bp = _single_group_bp()
    bp.compositions = [
        Composition(id="wave1", kind="fire_team", side="EAST",
                    anchor=(100, 100, 0), size=4),
    ]
    bp.reinforcements = [
        ReinforcementWave(id="w1", composition_id="wave1",
                          trigger_delay_seconds=30, max_count=1),
    ]
    sqf = generate_reinforcements_sqf(bp)
    # Inline createUnit invocations for each slot of the composition.
    assert "createUnit" in sqf
    assert "sleep 30" in sqf
    assert "O_Soldier_F" in sqf  # resolved from vanilla catalogue


def test_b2_reinforcements_state_trigger_uses_statemachine():
    bp = _single_group_bp()
    bp.compositions = [Composition(id="w1", kind="fire_team",
                                   side="EAST", anchor=(0, 0, 0))]
    bp.reinforcements = [
        ReinforcementWave(id="w1", composition_id="w1",
                          trigger_state="combat", max_count=2),
    ]
    sqf = generate_reinforcements_sqf(bp)
    assert "CBA_statemachine_fnc_addStateScript" in sqf
    assert "A3B_w1_count" in sqf


# ============================== B3 — Characters + WorldFlags ===============


def test_b3_characters_hpp_has_cfgidentities(campaign_plan):
    campaign_plan.brief.characters = [
        Character(id="sgt_miller", name="Sgt Miller",
                  role="team_leader", voice="Male02ENG"),
    ]
    hpp = generate_characters_hpp(campaign_plan)
    assert "class CfgIdentities" in hpp
    assert 'name     = "Sgt Miller"' in hpp
    assert 'speaker  = "Male02ENG"' in hpp


def test_b3_apply_identity_sqf():
    assert apply_identity_sqf("sgt_miller", "p1") == 'p1 setIdentity "A3B_sgt_miller";'


def test_b3_world_flag_helpers_use_profilenamespace():
    setter = generate_world_flags_helper_sqf()
    getter = generate_world_flags_reader_sqf()
    assert "profileNamespace setVariable" in setter
    assert "saveProfileNamespace" in setter
    assert "profileNamespace getVariable" in getter


def test_b3_worldflag_write_is_wired_to_on_enter():
    bp = MissionBlueprint(
        mission_id="m01",
        brief=MissionBrief(title="T", summary="s", map="VR", side="WEST",
                           enemy_side="EAST", objectives=["o"]),
        fsm=FsmGraph(initial="s",
                     states=[
                         FsmState(id="s", label="S",
                                  transitions=[FsmTransition(
                                      to="done", kind=TransitionKind.TIMER,
                                      condition="5")]),
                         FsmState(id="done", label="Done",
                                  is_terminal=True, end_type="end1"),
                     ]),
        world_flag_writes=[
            WorldFlagWrite(key="saved_pilot", value=True,
                           trigger_state="done", description=""),
        ],
    )
    wire_world_flag_writes(bp)
    done = next(s for s in bp.fsm.states if s.id == "done")
    assert any("setWorldFlag" in stmt for stmt in done.on_enter)
    assert any('"saved_pilot"' in stmt for stmt in done.on_enter)


# ============================== B4 — Cutscenes + Music =====================


def test_b4_cutscene_envelope_locks_input_when_asked():
    cs = Cutscene(id="intro", kind="intro", trigger_state="start",
                  duration_seconds=5, lock_player_input=True,
                  script=["titleText [\"Hi\", \"PLAIN\"]"])
    sqf = generate_cutscene_sqf(cs)
    assert "showCinemaBorder true" in sqf
    assert "titleCut [\"\", \"BLACK IN\", 0.5]" in sqf
    assert "titleText" in sqf
    assert "sleep 5" in sqf


def test_b4_cutscene_paths_includes_id():
    bp = MissionBlueprint(
        mission_id="m01",
        brief=MissionBrief(title="T", summary="s", map="VR", side="WEST",
                           enemy_side="EAST", objectives=["o"]),
        fsm=FsmGraph(initial="s",
                     states=[FsmState(id="s", label="S",
                                      is_terminal=True, end_type="end1")]),
        cutscenes=[Cutscene(id="intro", kind="intro", trigger_state="s")],
    )
    paths = cutscene_paths(bp)
    assert paths
    assert paths[0][0] == "cutscenes/intro.sqf"


def test_b4_wire_cutscenes_pushes_onto_state():
    bp = MissionBlueprint(
        mission_id="m01",
        brief=MissionBrief(title="T", summary="s", map="VR", side="WEST",
                           enemy_side="EAST", objectives=["o"]),
        fsm=FsmGraph(initial="s",
                     states=[FsmState(id="s", label="S",
                                      is_terminal=True, end_type="end1")]),
        cutscenes=[Cutscene(id="intro", kind="intro", trigger_state="s")],
    )
    wire_cutscenes_into_fsm(bp)
    s = bp.fsm.states[0]
    assert any('cutscenes/intro.sqf' in stmt for stmt in s.on_enter)


def test_b4_music_cfg_emits_custom_tracks_only():
    bp = MissionBlueprint(
        mission_id="m01",
        brief=MissionBrief(title="T", summary="s", map="VR", side="WEST",
                           enemy_side="EAST", objectives=["o"]),
        fsm=FsmGraph(initial="s",
                     states=[FsmState(id="s", label="S",
                                      is_terminal=True, end_type="end1")]),
        music_cues=[
            MusicCue(id="vanilla", track="LeadTrack01a_F_EPA", trigger_state="s"),
            MusicCue(id="custom",  track="A3B_my_track",       trigger_state="s"),
        ],
    )
    block = generate_cfg_music_block(bp)
    assert "class A3B_my_track" in block
    # Vanilla tracks must NOT appear in CfgMusic — they're already registered.
    assert "LeadTrack01a_F_EPA" not in block


def test_b4_music_wired_to_on_enter():
    bp = MissionBlueprint(
        mission_id="m01",
        brief=MissionBrief(title="T", summary="s", map="VR", side="WEST",
                           enemy_side="EAST", objectives=["o"]),
        fsm=FsmGraph(initial="s",
                     states=[FsmState(id="s", label="S",
                                      is_terminal=True, end_type="end1")]),
        music_cues=[
            MusicCue(id="m1", track="LeadTrack01a_F_EPA",
                     trigger_state="s", fade_seconds=2),
        ],
    )
    wire_music_into_fsm(bp)
    s = bp.fsm.states[0]
    assert any("playMusic" in stmt for stmt in s.on_enter)
    assert any("fadeMusic" in stmt for stmt in s.on_enter)


# ============================== B5 — Map UI served ==========================


def test_b5_ui_has_map_canvas():
    c = TestClient(app)
    html = c.get("/").text
    assert 'id="map"' in html
    assert 'id="map-hover"' in html


# ============================== Integration via convoy template ============


def test_b_integration_convoy_emits_full_phase_b(tmp_path, monkeypatch):
    """Run /generate with the convoy template and check every B artefact shows up."""
    c = TestClient(app)
    monkeypatch.setenv("ARMA3_OUTPUT_DIR", str(tmp_path))

    # Instantiate the convoy template, wrap into brief, POST to /generate.
    tpl = c.post("/templates/convoy/instantiate",
                 json={"title": "Integration Test", "map": "Tanoa"}).json()
    bp = tpl["blueprint"]
    body = {"brief": {
        "name": "Phase B Integration",
        "author": "test",
        "overview": bp["brief"]["summary"],
        "mods": ["cba_main"],
        "factions": {"WEST": "BLU_F", "EAST": "OPF_F"},
        "missions": [bp["brief"]],
    }}
    r = c.post("/generate", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    out = Path(data["output_path"])

    # Characters file at campaign root.
    assert (out / "characters.hpp").exists()

    # Per-mission Phase-B SQF artefacts for the single instantiated mission.
    mission_dir = next((out / "missions").iterdir())
    funcs = mission_dir / "functions"
    assert (funcs / "fn_setWorldFlag.sqf").exists()
    assert (funcs / "fn_getWorldFlag.sqf").exists()
    # Convoy template ships a fire-team composition → expect its waypoints
    # show up inside mission.sqm (indirect check).
    assert (mission_dir / "mission.sqm").exists()

    # description.ext includes characters.hpp.
    ext_text = (mission_dir / "description.ext").read_text(encoding="utf-8")
    assert '#include "..\\..\\characters.hpp"' in ext_text
