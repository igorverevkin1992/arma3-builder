"""WorldFlag read/write SQF helpers + Campaign-level conditional branches.

A ``WorldFlagWrite`` on a FSM state captures a fact about the current
mission (e.g. "saved_pilot = true") that needs to persist into the next
mission. The SQF emitter routes the write through ``A3B_fnc_setWorldFlag``
which wraps ``profileNamespace`` so the value survives across missions.

Campaign-level conditional transitions (e.g. "if saved_pilot → go to
mission 3A, else → mission 3B") are rendered by augmenting the Campaign
``Description.ext``'s mission block with a ``condition = "..."`` entry
and an alternate ``end1 = "other_mission_id"`` for the negative branch.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..protocols import MissionBlueprint


def generate_world_flags_helper_sqf() -> str:
    """Contents of ``functions/fn_setWorldFlag.sqf`` (single setter)."""
    return (
        "// fn_setWorldFlag.sqf — persist a flag through profileNamespace.\n"
        "// Usage: [\"saved_pilot\", true] call A3B_fnc_setWorldFlag;\n"
        "params [\n"
        "    [\"_key\", \"\", [\"\"]],\n"
        "    [\"_value\", nil]\n"
        "];\n"
        "if (_key isEqualTo \"\") exitWith { false };\n"
        "profileNamespace setVariable [format [\"A3B_wf_%1\", _key], _value];\n"
        "saveProfileNamespace;\n"
        "diag_log format [\"[A3B] world flag %1 = %2\", _key, _value];\n"
        "true\n"
    )


def generate_world_flags_reader_sqf() -> str:
    """Contents of ``functions/fn_getWorldFlag.sqf`` (single getter)."""
    return (
        "// fn_getWorldFlag.sqf — read a previously written flag.\n"
        "// Usage: private _saved = \"saved_pilot\" call A3B_fnc_getWorldFlag;\n"
        "params [[\"_key\", \"\", [\"\"]]];\n"
        "if (_key isEqualTo \"\") exitWith { nil };\n"
        "profileNamespace getVariable [format [\"A3B_wf_%1\", _key], nil]\n"
    )


def wire_world_flag_writes(blueprint: MissionBlueprint) -> None:
    """Inline world-flag writes into the owning FSM states' ``on_enter``.

    The Narrative Director declares ``world_flag_writes`` on the blueprint
    (cross-mission-oriented data), but the runtime side-effect must fire
    when the FSM enters the trigger state. The simplest wiring is to push
    the SQF `setWorldFlag` call onto the matching state's on_enter list,
    which ``fsm.py`` then emits as part of the state-machine callback.
    """
    by_id = {s.id: s for s in blueprint.fsm.states}
    for w in blueprint.world_flag_writes:
        state = by_id.get(w.trigger_state)
        if state is None:
            continue
        state.on_enter.append(
            f'["{w.key}", {_sqf_value(w.value)}] call A3B_fnc_setWorldFlag'
        )


def _sqf_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "nil"
    return '"' + str(value).replace('"', '""') + '"'


# --------------------------------------------------------------------------- #
# Campaign-level conditional branches
# --------------------------------------------------------------------------- #


@dataclass
class ConditionalBranch:
    """One `if flag → mission` edge in the campaign graph."""
    from_mission: str
    end_type: str
    flag_key: str
    expected_value: object
    then_mission: str
    else_mission: str


def conditional_branch_block(branch: ConditionalBranch) -> str:
    """Render a Campaign Description.ext entry for a conditional end.

    Arma's campaign syntax supports `<endName> = "missionId"` plus a
    `<endName>_cond = "SQF expression"` override. We emit both so the
    engine evaluates the flag and picks the right next mission.
    """
    expr_val = _sqf_value(branch.expected_value)
    cond = f'(["{branch.flag_key}"] call A3B_fnc_getWorldFlag) == {expr_val}'
    return (
        f'        // conditional: if {branch.flag_key} == {branch.expected_value} → {branch.then_mission}\n'
        f'        {branch.end_type} = "{branch.then_mission}";\n'
        f'        {branch.end_type}_cond = "{cond}";\n'
        f'        {branch.end_type}_alt  = "{branch.else_mission}";\n'
    )
