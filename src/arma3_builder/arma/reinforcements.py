"""Reinforcement wave scheduler → SQF.

A ``ReinforcementWave`` is a delayed spawn keyed off an FSM state entry or
a timer. We resolve the referenced ``Composition`` and emit SQF that:

  1. Waits for the trigger (state-machine hook via CBA, *or* `sleep N`).
  2. Invokes the composition-expansion helper from Scripter's preloaded
     functions, OR inlines ``createUnit`` + ``moveInAny`` calls.

Everything runs server-side. The engine broadcasts the newly spawned
units to clients automatically through the ordinary MP replication path.
"""
from __future__ import annotations

from ..protocols import Composition, MissionBlueprint, ReinforcementWave


def _sqf_spawn_inline(comp: Composition, wave_idx: int) -> str:
    """Emit per-composition inline spawn code.

    We don't try to share the compositions.expand_composition output
    SQF-side — instead we inline `createUnit` calls so the generated
    script is self-contained and doesn't require a preprocessor pass.
    """
    from . import compositions as _c

    units, _wps = _c.expand_composition(comp)
    lines = [
        f'// Wave "{comp.id}" — {len(units)} unit(s).',
        '_grp = createGroup [' + _side_token(comp.side) + ', true];',
    ]
    for u in units:
        lines.append(
            f'"{u.classname}" createUnit '
            f'[[{u.position[0]:.1f},{u.position[1]:.1f},{u.position[2]:.1f}], '
            f'_grp, "this allowFleeing 0", 0.6, '
            f'"{"CORPORAL" if u.is_leader else "PRIVATE"}"];'
        )
    # Give the group a sensible combat posture.
    lines.append('_grp setCombatMode "RED";')
    lines.append('_grp setBehaviour "AWARE";')
    # Send them towards the player as a simple default.
    lines.append('_wp = _grp addWaypoint [getPos player, 0];')
    lines.append('_wp setWaypointType "SAD";')
    return "\n".join(lines)


def _side_token(side: str) -> str:
    return {
        "WEST": "west",
        "EAST": "east",
        "INDEPENDENT": "resistance",
        "CIVILIAN": "civilian",
    }.get(side, "east")


def generate_reinforcements_sqf(blueprint: MissionBlueprint) -> str:
    """Return ``functions/fn_reinforcements.sqf``."""
    waves = blueprint.reinforcements
    if not waves:
        return "// No reinforcement waves.\n"

    comp_by_id = {c.id: c for c in blueprint.compositions}

    lines = [
        "// fn_reinforcements.sqf — schedule delayed spawns.",
        "// Called from initServer after A3B_fnc_initFsm so the state",
        "// machine is available for state-triggered waves.",
        "if (!isServer) exitWith {};",
        "private _grp = grpNull;",
        "private _wp = objNull;",
        "",
    ]
    for i, wave in enumerate(waves):
        comp = comp_by_id.get(wave.composition_id)
        if comp is None:
            lines.append(
                f'// SKIP wave "{wave.id}": composition "{wave.composition_id}" not found'
            )
            continue
        spawn_code = _sqf_spawn_inline(comp, i)
        body = '\n    '.join(spawn_code.splitlines())

        trigger_block = _trigger_block(wave, body)
        lines.append(f'// Wave: {wave.id}')
        lines.append(trigger_block)
        lines.append("")
    return "\n".join(lines) + "\n"


def _trigger_block(wave: ReinforcementWave, body: str) -> str:
    """Wrap the spawn body in a server-side spawn {} with the correct trigger."""
    if wave.trigger_state:
        # Use the FSM state-machine addStateScript. Fires N copies up to
        # max_count.
        return (
            f'[missionNamespace getVariable ["A3B_stateMachine", objNull], '
            f'"{wave.trigger_state}", {{\n'
            f'    params ["_ignored"];\n'
            f'    if (missionNamespace getVariable ["A3B_{wave.id}_count", 0] >= {wave.max_count}) exitWith {{}};\n'
            f'    missionNamespace setVariable ["A3B_{wave.id}_count", '
            f'(missionNamespace getVariable ["A3B_{wave.id}_count", 0]) + 1];\n'
            f'    {body}\n'
            f'}}, "enter"] call CBA_statemachine_fnc_addStateScript;'
        )
    if wave.trigger_delay_seconds is not None:
        return (
            f'[] spawn {{\n'
            f'    sleep {wave.trigger_delay_seconds};\n'
            f'    {body}\n'
            f'}};'
        )
    # No trigger → fire immediately.
    return f'[] spawn {{\n    {body}\n}};'
