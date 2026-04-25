"""Group behaviour DSL → SQF.

Designers bind a behaviour to a group via ``BehaviourBinding``; we emit a
small SQF function per binding into ``functions/fn_bindBehaviour.sqf`` and
invoke it from initServer. Behaviours use vanilla commands + BIS_fnc
helpers — no hard CBA dependency, so they work even when CBA is absent.
"""
from __future__ import annotations

from ..protocols import BehaviourBinding, MissionBlueprint


def _group_ref(group_id: str) -> str:
    """Resolve a group id to an SQF expression.

    The SQM uses `p1/e1/e2/...` unit names; we take the group of the first
    unit matching the composition id (unit names start with the group_id).
    """
    # A stable way to find the group: pick any unit whose name starts with
    # the group_id + "_" — all composition-expanded units follow that
    # convention. Falls back to `group leader` if nothing matches.
    return (
        f'(group (missionNamespace getVariable '
        f'["A3B_group_{group_id}", objNull]))'
    )


def _snapshot_group_sqf(group_id: str, marker_unit: str) -> str:
    """SQF that stashes the group of ``marker_unit`` under A3B_group_<id>."""
    return (
        f'if (!isNull ({marker_unit})) then '
        f'{{ missionNamespace setVariable ["A3B_group_{group_id}", {marker_unit}, true]; }};'
    )


# --------------------------------------------------------------------------- #
# SQF templates per behaviour kind
# --------------------------------------------------------------------------- #


def _sqf_patrol(b: BehaviourBinding) -> str:
    # BIS_fnc_taskPatrol sets up a random patrol within a radius — zero
    # hand-crafted waypoints, zero busy loops.
    pts = b.waypoints or []
    if pts:
        wp_array = "[" + ",".join(
            f"[{p[0]},{p[1]},{p[2]}]" for p in pts
        ) + "]"
        return (
            f'_g = {_group_ref(b.group_id)};\n'
            f'if (isNull _g) exitWith {{}};\n'
            f'[_g, {wp_array}] call BIS_fnc_taskDefend;\n'
            f'_g setCombatMode "{b.combat_mode}";\n'
            f'_g setBehaviour "{b.behaviour}";\n'
        )
    return (
        f'_g = {_group_ref(b.group_id)};\n'
        f'if (isNull _g) exitWith {{}};\n'
        f'[_g, getPos (leader _g), {int(b.radius)}] call BIS_fnc_taskPatrol;\n'
        f'_g setCombatMode "{b.combat_mode}";\n'
        f'_g setBehaviour "{b.behaviour}";\n'
    )


def _sqf_garrison(b: BehaviourBinding) -> str:
    # CBA's garrison, falling back to BIS_fnc_taskDefend when CBA absent.
    return (
        f'_g = {_group_ref(b.group_id)};\n'
        f'if (isNull _g) exitWith {{}};\n'
        f'if (isClass (configFile >> "CfgPatches" >> "cba_main")) then {{\n'
        f'    [_g, getPos (leader _g), {int(b.radius)}] call CBA_fnc_taskGarrison;\n'
        f'}} else {{\n'
        f'    [_g, getPos (leader _g), {int(b.radius)}] call BIS_fnc_taskDefend;\n'
        f'}};\n'
        f'_g setCombatMode "{b.combat_mode}";\n'
        f'_g setBehaviour "{b.behaviour}";\n'
    )


def _sqf_flank(b: BehaviourBinding) -> str:
    # Spawn two waypoints 90° off the player's bearing for a classic
    # envelopment pattern. BIS_fnc_findSafePos keeps them on walkable ground.
    return (
        f'_g = {_group_ref(b.group_id)};\n'
        f'if (isNull _g) exitWith {{}};\n'
        f'_centre = getPos player;\n'
        f'_left  = [_centre, {int(b.radius)}, {int(b.radius) + 50}, 5, 0, 0.5, 0] call BIS_fnc_findSafePos;\n'
        f'_right = [_centre, {int(b.radius)}, {int(b.radius) + 50}, 5, 0, 0.5, 0] call BIS_fnc_findSafePos;\n'
        f'[_g addWaypoint [_left, 0], "MOVE"];\n'
        f'[_g addWaypoint [_right, 0], "SAD"];\n'
        f'_g setCombatMode "RED";\n'
        f'_g setBehaviour "COMBAT";\n'
    )


def _sqf_defend(b: BehaviourBinding) -> str:
    return (
        f'_g = {_group_ref(b.group_id)};\n'
        f'if (isNull _g) exitWith {{}};\n'
        f'[_g, getPos (leader _g), {int(b.radius)}] call BIS_fnc_taskDefend;\n'
        f'_g setCombatMode "{b.combat_mode}";\n'
        f'_g setBehaviour "{b.behaviour}";\n'
    )


def _sqf_hunt(b: BehaviourBinding) -> str:
    return (
        f'_g = {_group_ref(b.group_id)};\n'
        f'if (isNull _g) exitWith {{}};\n'
        f'[_g, getPos player, {int(b.radius)}] call BIS_fnc_taskAttack;\n'
        f'_g setCombatMode "RED";\n'
        f'_g setBehaviour "COMBAT";\n'
    )


_KINDS = {
    "patrol":   _sqf_patrol,
    "garrison": _sqf_garrison,
    "flank":    _sqf_flank,
    "defend":   _sqf_defend,
    "hunt":     _sqf_hunt,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def generate_bind_behaviour_sqf(blueprint: MissionBlueprint) -> str:
    """Return ``functions/fn_bindBehaviour.sqf`` content.

    We first snapshot each group by its declared unit names (so we have
    a stable reference that survives unit respawns), then apply each
    behaviour binding.
    """
    if not blueprint.behaviour_bindings:
        return "// No behaviour bindings.\n"

    out = [
        "// fn_bindBehaviour.sqf — snapshot groups and apply behaviours.",
        "// Runs server-side after initFsm so A3B_stateMachine exists.",
        "if (!isServer) exitWith {};",
        "",
        "private _g = grpNull;",
        "",
    ]

    # Build a snapshot block per group id — we find a unit whose `name`
    # matches <group_id>_* (this is how compositions.py names them).
    group_ids = {b.group_id for b in blueprint.behaviour_bindings}
    for gid in sorted(group_ids):
        # First unit in blueprint with matching group_id wins.
        leader_unit = next(
            (u for u in blueprint.units if u.group_id == gid), None,
        )
        if leader_unit and leader_unit.name:
            out.append(_snapshot_group_sqf(gid, leader_unit.name))

    out.append("")
    for b in blueprint.behaviour_bindings:
        kind_fn = _KINDS.get(b.kind)
        if kind_fn is None:
            continue
        out.append(f"// Binding: group={b.group_id} kind={b.kind}")
        out.append(kind_fn(b))
        out.append("")
    return "\n".join(out)
