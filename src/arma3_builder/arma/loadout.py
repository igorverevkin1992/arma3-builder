"""Loadout system.

Designers either provide explicit ``Loadout`` objects on the blueprint, or
leave them empty and let us synthesise a faction-appropriate kit from the
built-in catalogue. The SQF emitter produces two things:

1. ``loadouts/fn_applyLoadout.sqf`` — a function that wipes the player's
   gear and applies a Loadout by role_id. Called from initPlayerLocal.
2. Lobby `Params` entry in description.ext so players can pick a role.

The catalogue intentionally ships only vanilla + RHS_USAF. Mod authors can
extend it at runtime via ``register_loadout``.
"""
from __future__ import annotations

from ..protocols import Loadout, MissionBlueprint


# --------------------------------------------------------------------------- #
# Default catalogue (role_id -> Loadout). Vanilla BLUFOR baseline.
# --------------------------------------------------------------------------- #


_DEFAULTS: dict[str, Loadout] = {
    "team_leader": Loadout(
        role_id="team_leader", display_name="Team Leader",
        uniform="U_B_CombatUniform_mcam", vest="V_PlateCarrier2_rgr",
        headgear="H_HelmetB_camo", backpack="B_AssaultPack_mcamo",
        primary_weapon="arifle_MX_GL_F",
        primary_magazines=[("30Rnd_65x39_caseless_mag", 8), ("1Rnd_HE_Grenade_shell", 6)],
        handgun="hgun_P07_F",
        handgun_magazines=[("16Rnd_9x21_Mag", 3)],
        items=["FirstAidKit", "FirstAidKit", "SmokeShell", "SmokeShellBlue", "Chemlight_blue"],
        linked_items=["NVGoggles", "ItemMap", "ItemCompass", "ItemRadio", "ItemGPS", "ItemWatch"],
    ),
    "rifleman": Loadout(
        role_id="rifleman", display_name="Rifleman",
        uniform="U_B_CombatUniform_mcam", vest="V_PlateCarrier1_rgr",
        headgear="H_HelmetB", backpack="B_AssaultPack_mcamo",
        primary_weapon="arifle_MX_F",
        primary_magazines=[("30Rnd_65x39_caseless_mag", 10)],
        items=["FirstAidKit", "FirstAidKit", "SmokeShell", "HandGrenade"],
        linked_items=["NVGoggles", "ItemMap", "ItemCompass", "ItemRadio", "ItemWatch"],
    ),
    "autorifleman": Loadout(
        role_id="autorifleman", display_name="Auto Rifleman",
        uniform="U_B_CombatUniform_mcam", vest="V_PlateCarrierGL_rgr",
        headgear="H_HelmetB", backpack="B_AssaultPack_mcamo",
        primary_weapon="arifle_MX_SW_F",
        primary_magazines=[("100Rnd_65x39_caseless_mag", 4)],
        items=["FirstAidKit", "FirstAidKit", "SmokeShell"],
        linked_items=["NVGoggles", "ItemMap", "ItemCompass", "ItemRadio", "ItemWatch"],
    ),
    "medic": Loadout(
        role_id="medic", display_name="Medic",
        uniform="U_B_CombatUniform_mcam", vest="V_PlateCarrier1_rgr",
        headgear="H_HelmetB", backpack="B_Kitbag_mcamo",
        primary_weapon="arifle_MX_F",
        primary_magazines=[("30Rnd_65x39_caseless_mag", 8)],
        items=["FirstAidKit"] * 10 + ["Medikit"],
        linked_items=["NVGoggles", "ItemMap", "ItemCompass", "ItemRadio", "ItemWatch"],
    ),
    "marksman": Loadout(
        role_id="marksman", display_name="Marksman",
        uniform="U_B_GhillieSuit", vest="V_PlateCarrierSpec_rgr",
        headgear="H_Booniehat_mcamo",
        primary_weapon="srifle_EBR_F",
        primary_magazines=[("20Rnd_762x51_Mag", 10)],
        items=["FirstAidKit", "Rangefinder", "Binocular"],
        linked_items=["NVGoggles", "ItemMap", "ItemCompass", "ItemGPS", "ItemRadio"],
    ),
    "breacher": Loadout(
        role_id="breacher", display_name="Breacher / Demolitions",
        uniform="U_B_CombatUniform_mcam", vest="V_PlateCarrierGL_rgr",
        headgear="H_HelmetSpecB", backpack="B_AssaultPack_mcamo",
        primary_weapon="arifle_MX_F",
        primary_magazines=[("30Rnd_65x39_caseless_mag", 8)],
        items=["FirstAidKit", "FirstAidKit", "DemoCharge_Remote_Mag",
               "DemoCharge_Remote_Mag", "ToolKit", "MineDetector"],
        linked_items=["NVGoggles", "ItemMap", "ItemCompass", "ItemRadio", "ItemWatch"],
    ),
}


# RHS_USAF overrides — mod-aware roles. Only fields that differ from the
# vanilla baseline need to be set; the caller merges them with _DEFAULTS.
_RHS_USAF: dict[str, Loadout] = {
    "team_leader": Loadout(
        role_id="team_leader", display_name="Team Leader (USMC)",
        uniform="rhs_uniform_FROG01_m81", vest="rhsusf_iotv_ocp_Squadleader",
        headgear="rhsusf_ach_helmet_ocp", backpack="rhsusf_assault_eagleaiii_ocp",
        primary_weapon="rhs_weap_m4a1_carryhandle_grip",
        primary_magazines=[("rhs_mag_30Rnd_556x45_M855A1_Stanag", 10),
                           ("rhs_mag_M441_HE", 6)],
        handgun="rhsusf_weap_m1911a1",
        handgun_magazines=[("rhsusf_mag_7x45acp_MHP", 3)],
        items=["rhs_ifak", "rhs_ifak", "rhs_mag_m67", "rhs_mag_m67",
               "rhs_mag_an_m8hc", "rhs_mag_m18_green"],
        linked_items=["rhsusf_ANPVS_15", "ItemMap", "ItemCompass",
                      "ItemGPS", "ACRE_PRC343", "ItemWatch"],
    ),
    "rifleman": Loadout(
        role_id="rifleman", display_name="Rifleman (USMC)",
        uniform="rhs_uniform_FROG01_m81", vest="rhsusf_iotv_ocp_Rifleman",
        headgear="rhsusf_ach_helmet_ocp", backpack="rhsusf_assault_eagleaiii_ocp",
        primary_weapon="rhs_weap_m4a1_carryhandle",
        primary_magazines=[("rhs_mag_30Rnd_556x45_M855A1_Stanag", 10)],
        items=["rhs_ifak", "rhs_ifak", "rhs_mag_m67"],
        linked_items=["rhsusf_ANPVS_15", "ItemMap", "ItemCompass",
                      "ACRE_PRC343", "ItemWatch"],
    ),
    "medic": Loadout(
        role_id="medic", display_name="Corpsman (USMC)",
        uniform="rhs_uniform_FROG01_m81", vest="rhsusf_iotv_ocp_Medic",
        headgear="rhsusf_ach_helmet_ocp", backpack="rhsusf_assault_eagleaiii_medic_ocp",
        primary_weapon="rhs_weap_m4a1_carryhandle",
        primary_magazines=[("rhs_mag_30Rnd_556x45_M855A1_Stanag", 8)],
        items=["rhs_ifak"] * 12 + ["Medikit"],
        linked_items=["rhsusf_ANPVS_15", "ItemMap", "ItemCompass",
                      "ACRE_PRC343", "ItemWatch"],
    ),
}


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


_REGISTRY: dict[tuple[str, str], Loadout] = {
    (faction, role_id): loadout
    for faction, table in (("vanilla", _DEFAULTS), ("rhsusf_main", _RHS_USAF))
    for role_id, loadout in table.items()
}


def register_loadout(faction: str, loadout: Loadout) -> None:
    """Runtime hook for user-defined loadouts (mods, unit-custom kits)."""
    _REGISTRY[(faction, loadout.role_id)] = loadout


def resolve_loadouts(
    requested: list[Loadout] | None,
    *,
    faction_hint: str = "vanilla",
    roles: list[str] | None = None,
) -> list[Loadout]:
    """Return a list of Loadouts for the mission.

    Explicit user-provided Loadouts always win. If none are provided, pull
    from the registry for the given faction (fall back to vanilla).
    """
    if requested:
        return list(requested)
    roles = roles or ["team_leader", "rifleman", "autorifleman", "medic"]
    out: list[Loadout] = []
    for role in roles:
        kit = _REGISTRY.get((faction_hint, role)) or _REGISTRY.get(("vanilla", role))
        if kit is not None:
            out.append(kit)
    return out


# --------------------------------------------------------------------------- #
# SQF emitter
# --------------------------------------------------------------------------- #


def _sqf_array(items: list[str]) -> str:
    return "[" + ",".join(f'"{x}"' for x in items) + "]"


def _sqf_mag_array(mags: list[tuple[str, int]]) -> str:
    parts = []
    for classname, count in mags:
        parts.extend([f'"{classname}"'] * count)
    return "[" + ",".join(parts) + "]"


def _emit_one_loadout(loadout: Loadout) -> str:
    """Emit a single `if (_role == "rifleman") then { ... };` block."""
    out = [
        f'    case "{loadout.role_id}": {{',
        "        removeAllWeapons _u;",
        "        removeAllItems _u;",
        "        removeAllAssignedItems _u;",
        "        removeUniform _u;",
        "        removeVest _u;",
        "        removeBackpack _u;",
        "        removeHeadgear _u;",
        "        removeGoggles _u;",
    ]
    if loadout.uniform:
        out.append(f'        _u forceAddUniform "{loadout.uniform}";')
    if loadout.vest:
        out.append(f'        _u addVest "{loadout.vest}";')
    if loadout.headgear:
        out.append(f'        _u addHeadgear "{loadout.headgear}";')
    if loadout.goggles:
        out.append(f'        _u addGoggles "{loadout.goggles}";')
    if loadout.backpack:
        out.append(f'        _u addBackpack "{loadout.backpack}";')
    # Magazines BEFORE weapons so the engine auto-loads them.
    for classname, count in loadout.primary_magazines:
        out.append(
            f'        for "_i" from 1 to {count} do '
            f'{{ _u addItemToVest "{classname}" }};'
        )
    for classname, count in loadout.handgun_magazines:
        out.append(
            f'        for "_i" from 1 to {count} do '
            f'{{ _u addItemToUniform "{classname}" }};'
        )
    if loadout.primary_weapon:
        out.append(f'        _u addWeapon "{loadout.primary_weapon}";')
    if loadout.secondary_weapon:
        out.append(f'        _u addWeapon "{loadout.secondary_weapon}";')
    if loadout.handgun:
        out.append(f'        _u addWeapon "{loadout.handgun}";')
    for item in loadout.items:
        out.append(f'        _u addItemToVest "{item}";')
    for item in loadout.linked_items:
        out.append(f'        _u linkItem "{item}";')
    out.append("    };")
    return "\n".join(out)


def generate_loadout_sqf(loadouts: list[Loadout]) -> str:
    """Return ``functions/fn_applyLoadout.sqf`` content."""
    if not loadouts:
        return "// No loadouts configured; vanilla starting gear is preserved.\n"
    header = [
        "// fn_applyLoadout.sqf — applies a faction-aware loadout to _unit.",
        "// Usage: [player, \"team_leader\"] call A3B_fnc_applyLoadout;",
        "params [",
        "    [\"_u\", objNull, [objNull]],",
        "    [\"_role\", \"\", [\"\"]]",
        "];",
        "if (isNull _u) exitWith { false };",
        "",
        "switch (toLower _role) do {",
    ]
    blocks = [_emit_one_loadout(l) for l in loadouts]
    footer = [
        "    default {",
        "        diag_log format [\"[A3B] applyLoadout: unknown role %1\", _role];",
        "    };",
        "};",
        "true",
    ]
    return "\n".join(header + blocks + footer) + "\n"


def generate_loadout_hook_sqf(default_role: str = "rifleman") -> str:
    """Client-side hook that reads the lobby param and applies the loadout."""
    return (
        "// Loadout hook — called from initPlayerLocal. Reads the lobby \n"
        "// \"A3B_role\" param (integer index into the loadout list) or \n"
        "// defaults to rifleman.\n"
        "if (!hasInterface) exitWith {};\n"
        "waitUntil { !isNull player };\n"
        "\n"
        f'private _role = player getVariable ["A3B_role_override", "{default_role}"];\n'
        "[player, _role] call A3B_fnc_applyLoadout;\n"
        "true\n"
    )


def lobby_param_block(loadouts: list[Loadout]) -> str:
    """Emit a `class Params { class A3B_role { ... }; };` fragment.

    Players can pick their role from the lobby before the mission starts —
    the value is read by the loadout hook above.
    """
    if not loadouts:
        return ""
    values = ", ".join(str(i) for i in range(len(loadouts)))
    texts = ", ".join(f'"{l.display_name}"' for l in loadouts)
    return (
        "class Params\n"
        "{\n"
        "    class A3B_role\n"
        "    {\n"
        "        title = \"Starting role\";\n"
        f'        values[] = {{{values}}};\n'
        f'        texts[] = {{{texts}}};\n'
        "        default = 0;\n"
        "    };\n"
        "};\n"
    )


def loadout_addons(loadouts: list[Loadout]) -> set[str]:
    """Collect addon-ish hints from classname prefixes for AddonsMetaData."""
    addons: set[str] = set()
    for l in loadouts:
        for name in (
            [l.uniform, l.vest, l.headgear, l.goggles, l.backpack,
             l.primary_weapon, l.secondary_weapon, l.handgun]
            + l.items + l.linked_items
            + [c for c, _ in l.primary_magazines]
            + [c for c, _ in l.secondary_magazines]
            + [c for c, _ in l.handgun_magazines]
        ):
            if not name:
                continue
            if name.startswith("rhs_") or name.startswith("rhsusf_"):
                addons.add("rhsusf_main")
            if name.startswith("ACRE_"):
                addons.add("acre_main")
            if name.startswith("ace_"):
                addons.add("ace_main")
    return addons
