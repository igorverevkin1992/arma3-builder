from arma3_builder.arma.briefing import generate_briefing_sqf


def test_briefing_creates_diary_and_tasks(mission_blueprint):
    sqf = generate_briefing_sqf(mission_blueprint)
    assert "createDiaryRecord" in sqf
    assert "BIS_fnc_taskCreate" in sqf
    # JIP-safety guards.
    assert "if (!hasInterface) exitWith {};" in sqf
    assert "waitUntil { !isNull player };" in sqf


def test_briefing_no_busy_loops(mission_blueprint):
    sqf = generate_briefing_sqf(mission_blueprint)
    assert "while {true}" not in sqf
