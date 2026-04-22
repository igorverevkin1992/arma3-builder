"""FSM → CBA statemachine SQF translator.

Builds an SQF script that:
  * defines the function `A3B_fnc_initFsm` (registered via CfgFunctions, preInit=1)
  * creates a CBA state machine with one state per FsmState
  * registers transitions with explicit conditions (no busy loops)
"""
from __future__ import annotations

from ..protocols import FsmGraph, MissionBlueprint, TransitionKind


def generate_statemachine_sqf(blueprint: MissionBlueprint) -> str:
    """Returns the contents of `functions/fn_initFsm.sqf`."""
    fsm = blueprint.fsm
    out: list[str] = [
        "// Auto-generated CBA statemachine for mission FSM.",
        "// Uses CBA_statemachine to avoid scheduler busy loops.",
        "",
        "private _sm = [] call CBA_statemachine_fnc_create;",
        "",
    ]

    for state in fsm.states:
        out.append(_emit_state(state))
        out.append("")

    for state in fsm.states:
        for tr in state.transitions:
            out.append(_emit_transition(state.id, tr))

    out.extend([
        "",
        f'[_sm, "{fsm.initial}"] call CBA_statemachine_fnc_setInitialState;',
        "missionNamespace setVariable [\"A3B_stateMachine\", _sm, true];",
        "_sm",
    ])
    return "\n".join(out)


def _emit_state(state) -> str:
    on_enter = "; ".join(state.on_enter) or "/* no entry actions */"
    on_exit = "; ".join(state.on_exit) or "/* no exit actions */"
    end_call = ""
    if state.is_terminal and state.end_type:
        end_call = f'; ["{state.end_type}", true, 5, true, false] call BIS_fnc_endMission'
    return (
        f'[_sm, "{state.id}", '
        f'{{ {on_enter}{end_call} }}, '
        f'{{ {on_exit} }}] call CBA_statemachine_fnc_addState;'
    )


def _emit_transition(from_id: str, tr) -> str:
    if tr.kind == TransitionKind.TIMER:
        cond = f'(diag_tickTime - (missionNamespace getVariable [format ["A3B_t_%1", "{from_id}"], diag_tickTime])) > {float(tr.condition)}'
    elif tr.kind == TransitionKind.EVENT:
        return (
            f'[_sm, "{from_id}", "{tr.to}", {{true}}, "{tr.condition}"] '
            f'call CBA_statemachine_fnc_addTransition;'
        )
    else:
        cond = tr.condition or "true"
    return (
        f'[_sm, "{from_id}", "{tr.to}", {{ {cond} }}, ""] '
        f'call CBA_statemachine_fnc_addTransition;'
    )


def diagram_for_blueprint(blueprint: MissionBlueprint) -> dict:
    """Returns a node-graph payload consumable by a frontend node editor (Phase 4)."""
    fsm: FsmGraph = blueprint.fsm
    return {
        "initial": fsm.initial,
        "nodes": [
            {
                "id": s.id,
                "label": s.label,
                "terminal": s.is_terminal,
                "endType": s.end_type,
            }
            for s in fsm.states
        ],
        "edges": [
            {
                "from": s.id,
                "to": t.to,
                "kind": t.kind.value,
                "condition": t.condition,
            }
            for s in fsm.states
            for t in s.transitions
        ],
    }
