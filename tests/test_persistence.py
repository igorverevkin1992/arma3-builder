from arma3_builder.arma.persistence import (
    generate_end_hook_sqf,
    generate_load_progress_sqf,
    generate_save_progress_sqf,
)


def test_save_progress_uses_profilenamespace():
    sqf = generate_save_progress_sqf()
    assert "profileNamespace setVariable" in sqf
    assert "saveProfileNamespace" in sqf


def test_load_progress_reads_profilenamespace():
    sqf = generate_load_progress_sqf()
    assert "profileNamespace getVariable" in sqf


def test_end_hook_registers_handler():
    sqf = generate_end_hook_sqf("m01_x")
    assert "addMissionEventHandler" in sqf
    assert "\"Ended\"" in sqf
    assert "m01_x_endType" in sqf
