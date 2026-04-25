"""Generate SQF helpers that persist campaign progress via ``profileNamespace``.

Two functions are emitted into every mission:

  A3B_fnc_saveProgress   [[key, value], ...]  → stores per-campaign values
  A3B_fnc_loadProgress   key                  → reads them

Additionally, `onMissionEnd` hooks save the FSM's terminal state so subsequent
missions can branch on the previous outcome — the design goal the TZ calls
"глубоко вариативные сценарии".
"""
from __future__ import annotations


def generate_save_progress_sqf() -> str:
    return (
        "// fn_saveProgress.sqf — persist key/value pairs in profileNamespace.\n"
        "// Usage: [[\"key1\", value1], [\"key2\", value2]] call A3B_fnc_saveProgress;\n"
        "params [[\"_pairs\", [], [[]]]];\n"
        "{\n"
        "    _x params [\"_key\", \"_value\"];\n"
        "    profileNamespace setVariable [format [\"A3B_%1\", _key], _value];\n"
        "} forEach _pairs;\n"
        "saveProfileNamespace;\n"
        "true\n"
    )


def generate_load_progress_sqf() -> str:
    return (
        "// fn_loadProgress.sqf — read a previously persisted value.\n"
        "// Usage: private _val = \"myKey\" call A3B_fnc_loadProgress;\n"
        "params [[\"_key\", \"\", [\"\"]]];\n"
        "profileNamespace getVariable [format [\"A3B_%1\", _key], nil]\n"
    )


def generate_end_hook_sqf(mission_id: str) -> str:
    """Register an onMissionEnd handler that saves the final FSM state."""
    return (
        f"// Auto-save the FSM terminal state for mission {mission_id}\n"
        f"if (!isServer) exitWith {{}};\n"
        "addMissionEventHandler [\"Ended\", {\n"
        "    params [\"_endType\"];\n"
        f"    [[\"{mission_id}_endType\", _endType]] call A3B_fnc_saveProgress;\n"
        "}];\n"
    )
