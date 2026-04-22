from arma3_builder.arma.fsm import diagram_for_blueprint, generate_statemachine_sqf


def test_statemachine_sqf_uses_cba(mission_blueprint):
    sqf = generate_statemachine_sqf(mission_blueprint)
    # Initial state now passed to fnc_create — not a separate setInitialState call.
    assert '["start"] call CBA_statemachine_fnc_create' in sqf
    assert "CBA_statemachine_fnc_addState" in sqf
    assert "CBA_statemachine_fnc_addTransition" in sqf
    # Terminal state must call BIS_fnc_endMission with correct 3-arg signature.
    assert "BIS_fnc_endMission" in sqf
    assert '["end1", true, true] call BIS_fnc_endMission' in sqf


def test_no_busy_loops_in_fsm_output(mission_blueprint):
    sqf = generate_statemachine_sqf(mission_blueprint)
    assert "while {true}" not in sqf
    assert "while{true}" not in sqf


def test_diagram_export(mission_blueprint):
    diagram = diagram_for_blueprint(mission_blueprint)
    assert diagram["initial"] == "start"
    assert {n["id"] for n in diagram["nodes"]} == {"start", "end"}
    assert diagram["edges"][0]["from"] == "start"
    assert diagram["edges"][0]["to"] == "end"
