"""FSM → CBA statemachine SQF translator.

Builds an SQF script that:
  * defines the function `A3B_fnc_initFsm` (registered via CfgFunctions, preInit=1)
  * creates a CBA state machine with one state per FsmState
  * registers transitions with explicit conditions (no busy loops)

Uses the real CBA_statemachine public API:

  fnc_create(initialStateName)            -> state machine object
  fnc_addState(sm, stateName)             -> add a state
  fnc_addStateScript(sm, stateName, code, "enter"|"exit"|"doing")
  fnc_addTransition(sm, from, to, condition[, event][, code])
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
        f'private _sm = ["{fsm.initial}"] call CBA_statemachine_fnc_create;',
        "",
    ]

    # 1. Register states.
    for state in fsm.states:
        out.append(f'[_sm, "{state.id}"] call CBA_statemachine_fnc_addState;')

    out.append("")

    # 2. Register state enter/exit scripts (only if there is code to run).
    for state in fsm.states:
        enter_code = _state_enter_block(state)
        if enter_code:
            out.append(
                f'[_sm, "{state.id}", {{ {enter_code} }}, "enter"] '
                f'call CBA_statemachine_fnc_addStateScript;'
            )
        if state.on_exit:
            exit_code = "; ".join(state.on_exit)
            out.append(
                f'[_sm, "{state.id}", {{ {exit_code} }}, "exit"] '
                f'call CBA_statemachine_fnc_addStateScript;'
            )

    out.append("")

    # 3. Register transitions.
    for state in fsm.states:
        for tr in state.transitions:
            out.append(_emit_transition(state.id, tr))

    out.extend([
        "",
        'missionNamespace setVariable ["A3B_stateMachine", _sm, true];',
        "_sm",
    ])
    return "\n".join(out)


def _state_enter_block(state) -> str:
    parts: list[str] = []
    if state.on_enter:
        parts.append("; ".join(state.on_enter))
    if state.is_terminal and state.end_type:
        # Modern signature: ["endName", isVictory, fadeOut]
        is_victory = "false" if state.end_type == "loser" else "true"
        parts.append(f'["{state.end_type}", {is_victory}, true] call BIS_fnc_endMission')
    return "; ".join(parts)


def _emit_transition(from_id: str, tr) -> str:
    if tr.kind == TransitionKind.TIMER:
        seconds = float(tr.condition or 0)
        cond = (
            f'(diag_tickTime - (missionNamespace getVariable '
            f'[format ["A3B_t_%1", "{from_id}"], diag_tickTime])) > {seconds}'
        )
    else:
        cond = tr.condition.strip() or "true"
    return (
        f'[_sm, "{from_id}", "{tr.to}", {{ {cond} }}] '
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
                "onEnter": s.on_enter,
                "onExit": s.on_exit,
            }
            for s in fsm.states
        ],
        "edges": [
            {
                "from": s.id,
                "to": t.to,
                "kind": t.kind.value,
                "condition": t.condition,
                "description": t.description,
            }
            for s in fsm.states
            for t in s.transitions
        ],
    }
