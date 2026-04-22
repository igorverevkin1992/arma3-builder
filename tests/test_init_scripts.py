from arma3_builder.arma.init_scripts import (
    generate_init_player_local,
    generate_init_server,
    generate_init_sqf,
)


def test_init_server_is_server_only(mission_blueprint):
    sqf = generate_init_server(mission_blueprint)
    assert "if (!isServer) exitWith {};" in sqf
    assert "enableDynamicSimulationSystem true" in sqf
    # GC for the 144 group limit lives in fn_repairLoop (PFH-based).
    assert "A3B_fnc_repairLoop" in sqf
    assert "A3B_fnc_initFsm" in sqf


def test_init_player_local_is_jip_safe(mission_blueprint):
    sqf = generate_init_player_local(mission_blueprint)
    assert "params" in sqf
    assert "briefing.sqf" in sqf
    # Must not put server-side spawn logic in the player local script.
    assert "deleteGroup" not in sqf


def test_init_sqf_is_lightweight(mission_blueprint):
    sqf = generate_init_sqf(mission_blueprint)
    assert "execVM" not in sqf  # heavy logic must not live in init.sqf
    assert "while {true}" not in sqf
