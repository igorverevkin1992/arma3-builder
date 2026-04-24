"""Generate init.sqf, initServer.sqf, initPlayerLocal.sqf with correct locality."""
from __future__ import annotations

from ..protocols import MissionBlueprint


def generate_init_sqf(blueprint: MissionBlueprint) -> str:
    return (
        "// init.sqf — runs on server AND every client. Keep it lightweight.\n"
        '#include "macros.hpp"\n'
        "\n"
        "A3B_missionStart = diag_tickTime;\n"
        f'A3B_missionTitle = "{_safe(blueprint.brief.title)}";\n'
        "\n"
        "// FSM bootstrap is handled by a CfgFunctions preInit hook.\n"
        "publicVariable \"A3B_missionTitle\";\n"
    )


def generate_init_server(blueprint: MissionBlueprint) -> str:
    """Server-only logic: dyn-sim, AI spawn, task registration, FSM start.

    initFsm and registerTasks are registered in CfgFunctions WITHOUT preInit,
    so we own the lifecycle here. Calling them from one place (server only)
    avoids the double-init bug that the earlier preInit + manual-call combo
    had. Tasks are created on the server and BIS_fnc_taskCreate broadcasts
    them automatically.
    """
    units_count = len(blueprint.units)
    addons = ", ".join(f'"{a}"' for a in blueprint.addons) or '"a3"'

    return (
        "// initServer.sqf — server / hosted host only.\n"
        "if (!isServer) exitWith {};\n"
        "\n"
        "// Dynamic Simulation: freeze AI outside the player envelope to save CPU.\n"
        "enableDynamicSimulationSystem true;\n"
        '"Group" setDynamicSimulationDistance 1000;\n'
        '"Vehicle" setDynamicSimulationDistance 1500;\n'
        '"EmptyVehicle" setDynamicSimulationDistance 800;\n'
        '"IsMoving" setDynamicSimulationDistanceCoef 1.5;\n'
        "\n"
        "// Garbage collector — registered as a CBA per-frame handler in fn_repairLoop.\n"
        "[] call A3B_fnc_repairLoop;\n"
        "\n"
        "// Register tasks BEFORE the FSM starts changing their state.\n"
        "[] call A3B_fnc_registerTasks;\n"
        "\n"
        "// FSM is started here so it owns server-authoritative state. The\n"
        "// state machine is stored in missionNamespace under \"A3B_stateMachine\".\n"
        "[] call A3B_fnc_initFsm;\n"
        "\n"
        "// Phase B — bind AI behaviours AFTER the FSM exists so behaviours that\n"
        "// reference A3B_stateMachine resolve correctly.\n"
        "if (!isNil \"A3B_fnc_bindBehaviour\") then { [] call A3B_fnc_bindBehaviour; };\n"
        "if (!isNil \"A3B_fnc_reinforcements\") then { [] call A3B_fnc_reinforcements; };\n"
        "\n"
        "// Phase C — spawn virtual arsenals declared on the blueprint.\n"
        "if (!isNil \"A3B_fnc_spawnArsenals\") then { [] call A3B_fnc_spawnArsenals; };\n"
        "\n"
        f"diag_log format [\"[A3B] mission started, %1 placed units, addons: {addons}\", {units_count}];\n"
    )


def generate_init_player_local(blueprint: MissionBlueprint) -> str:
    """Client-local UI, gear, JIP-safe addActions, briefing init."""
    has_loadouts = bool(blueprint.loadouts) or True  # Scripter resolves defaults
    has_support = bool(blueprint.support_assets)

    loadout_call = (
        '0 = [] spawn { call (compile preprocessFileLineNumbers "loadoutHook.sqf") };\n'
        if has_loadouts else ""
    )
    support_call = (
        '[] call A3B_fnc_registerSupportActions;\n'
        if has_support else ""
    )

    return (
        "// initPlayerLocal.sqf — runs on each client at start AND on JIP.\n"
        "params [\"_player\", \"_didJIP\"];\n"
        "if (isNull _player) then { _player = player };\n"
        "waitUntil { !isNull _player };\n"
        "\n"
        '// Apply role-appropriate gear (reads the lobby `A3B_role` param).\n'
        f"{loadout_call}"
        "\n"
        "// Register on-call support addActions (CAS, arty, medevac, ...).\n"
        f"{support_call}"
        "\n"
        "// Briefing — must be local, runs again for JIP clients automatically.\n"
        '0 = [] spawn { call (compile preprocessFileLineNumbers "briefing.sqf") };\n'
        "\n"
        '// Persistent local UI hint.\n'
        f'hint parseText "<t size=\'1.2\'>{_safe(blueprint.brief.title)}</t>";\n'
    )


def macros_header() -> str:
    """A small header used by init.sqf — keeps macro discipline mod-safe."""
    return (
        "// macros.hpp — auto-generated. Keep lightweight; included from init.sqf.\n"
        "#define A3B_DEBUG 0\n"
        "#define A3B_LOG(MSG) if (A3B_DEBUG > 0) then { diag_log format [\"[A3B] %1\", MSG] };\n"
    )


def _safe(s: str) -> str:
    return s.replace('"', '""').replace("\n", " ").strip()
