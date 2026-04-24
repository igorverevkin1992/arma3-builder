"""Virtual arsenal emitter — ACE or BIS.

An arsenal lets players re-kit between engagements. We support both:

  * ``ace``  — ``["AmmoboxInit", [_box, true]] call ace_arsenal_fnc_initBox``
  * ``bis``  — ``["Open", [true, _box]] call BIS_fnc_arsenal`` via addAction

The box is spawned at the arsenal's position, or near the first player if
unset. Emitted SQF runs server-side (spawn) with client-local addAction
wiring replicated via public variable.
"""
from __future__ import annotations

from ..protocols import MissionBlueprint, VirtualArsenal


def _spawn_line(arsenal: VirtualArsenal) -> str:
    if arsenal.position is not None:
        px, py, pz = arsenal.position
        pos_expr = f"[{px:.1f}, {py:.1f}, {pz:.1f}]"
    else:
        pos_expr = "(getPosATL player) vectorAdd [2, 0, 0]"
    return (
        f'_box_{arsenal.id} = createVehicle '
        f'["{arsenal.object_classname}", {pos_expr}, [], 0, "CAN_COLLIDE"];\n'
        f'publicVariable "_box_{arsenal.id}";'
    )


def _ace_init(arsenal: VirtualArsenal) -> str:
    fl = arsenal.faction_whitelist or ""
    # ACE's signature: [box, allowed, restrictDefault]
    if fl:
        return (
            f'[_box_{arsenal.id}, true, "{fl}"] '
            f'call ace_arsenal_fnc_initBox;'
        )
    return f'[_box_{arsenal.id}, true] call ace_arsenal_fnc_initBox;'


def _bis_init(arsenal: VirtualArsenal) -> str:
    return (
        f'_box_{arsenal.id} addAction [\n'
        f'    "<t color=\'#66ff66\'>Open Arsenal</t>",\n'
        f'    {{ ["Open", [true, (_this select 0), (_this select 1)]] '
        f'call BIS_fnc_arsenal; }},\n'
        f'    nil, 1.5, true, true, "", "true", 4, false, "", ""\n'
        f'];'
    )


def generate_arsenal_server_sqf(blueprint: MissionBlueprint) -> str:
    """Server-side: spawn boxes (initServer hook)."""
    if not blueprint.arsenals:
        return "// No arsenals configured.\n"
    out = [
        "// fn_spawnArsenals.sqf — server-side arsenal spawner.",
        "if (!isServer) exitWith {};",
        "",
    ]
    for a in blueprint.arsenals:
        out.append(f"// Arsenal: {a.id}")
        out.append(_spawn_line(a))
        out.append("")
    out.append("true\n")
    return "\n".join(out)


def generate_arsenal_client_sqf(blueprint: MissionBlueprint) -> str:
    """Client-side: wire up ACE/BIS init for each spawned arsenal box.

    We ``waitUntil`` for the box to propagate (publicVariable) then apply
    the right initialiser. This runs in both SP and MP.
    """
    if not blueprint.arsenals:
        return "// No arsenals to wire on clients.\n"
    out = [
        "// fn_initArsenalsClient.sqf — per-client arsenal wiring.",
        "if (!hasInterface) exitWith {};",
        "waitUntil { !isNull player };",
        "",
    ]
    for a in blueprint.arsenals:
        init = _ace_init(a) if a.kind == "ace" else _bis_init(a)
        out.append(f'waitUntil {{ !isNil "_box_{a.id}" }};')
        out.append(init)
        out.append("")
    out.append("true\n")
    return "\n".join(out)


def arsenal_addons(blueprint: MissionBlueprint) -> set[str]:
    """Return addons that must be declared given the configured arsenals."""
    addons: set[str] = set()
    for a in blueprint.arsenals:
        if a.kind == "ace":
            addons.add("ace_arsenal")
    return addons
