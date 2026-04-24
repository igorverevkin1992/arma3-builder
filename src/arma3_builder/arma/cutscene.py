"""Cutscene SQF emitter.

A ``Cutscene`` ties a scripted camera sequence to an FSM state entry. We
wrap the designer's SQF `script` list in a standard envelope:

  1. Optionally lock player input (disables `showHUD`, `enableSimulation`
     on the player vehicle, fades to black).
  2. Runs the designer's statements in sequence.
  3. Restores state after ``duration_seconds`` and fades back in.

Intro cutscenes also pause the FSM until the player has taken control
again (``lock_player_input=false`` short-circuits that for interludes
that can run while the player keeps fighting).
"""
from __future__ import annotations

from ..protocols import Cutscene, MissionBlueprint


def generate_cutscene_sqf(cutscene: Cutscene) -> str:
    """Render a single cutscene script.

    Assembled as explicit string concatenation — SQF's code-block `{...}`
    would otherwise collide with str.format's substitution braces.
    """
    lock = "true" if cutscene.lock_player_input else "false"
    body = "\n".join(cutscene.script) if cutscene.script else "// no custom statements"
    duration = max(1, cutscene.duration_seconds)
    return (
        'if (!hasInterface) exitWith {};\n'
        f'private _lock = {lock};\n'
        'private _prevHUD = shownHUD;\n'
        '\n'
        'if (_lock) then {\n'
        '    showCinemaBorder true;\n'
        '    0 fadeSound 0;\n'
        '    titleCut ["", "BLACK IN", 0.5];\n'
        '    enableRadio false;\n'
        '};\n'
        '\n'
        'private _cam = "camera" camCreate (getPosATL player);\n'
        '_cam cameraEffect ["internal", "back"];\n'
        '_cam camCommit 0;\n'
        'showHUD false;\n'
        '\n'
        '// -- designer-supplied statements --\n'
        f'{body}\n'
        '\n'
        '// -- wind-down --\n'
        f'sleep {duration};\n'
        '_cam cameraEffect ["terminate", "back"];\n'
        'camDestroy _cam;\n'
        'showHUD _prevHUD;\n'
        '\n'
        'if (_lock) then {\n'
        '    showCinemaBorder false;\n'
        '    titleCut ["", "BLACK OUT", 1.0];\n'
        '    0 fadeSound 1;\n'
        '    enableRadio true;\n'
        '};\n'
    )


def wire_cutscenes_into_fsm(blueprint: MissionBlueprint) -> None:
    """Inject a `spawn` into each trigger state's on_enter that runs the cut.

    Running the cutscene in a ``spawn`` means the FSM callback returns
    immediately; the cinematic plays asynchronously and the state can still
    transition when its own conditions fire (or `lock_player_input=true`
    halts the player, in which case transitions that depend on player
    movement naturally wait).
    """
    by_id = {s.id: s for s in blueprint.fsm.states}
    for cs in blueprint.cutscenes:
        state = by_id.get(cs.trigger_state)
        if state is None:
            continue
        state.on_enter.append(
            f'0 = [] spawn {{ call (compile '
            f'preprocessFileLineNumbers "cutscenes/{cs.id}.sqf") }}'
        )


def cutscene_paths(blueprint: MissionBlueprint) -> list[tuple[str, str]]:
    """Return ``[(relative_path, content), ...]`` for every cutscene."""
    return [
        (f"cutscenes/{cs.id}.sqf", generate_cutscene_sqf(cs))
        for cs in blueprint.cutscenes
    ]
