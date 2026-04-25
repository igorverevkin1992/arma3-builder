"""Generate on-call support-asset SQF (CAS, artillery, medevac, transport).

Designers list ``SupportAsset`` entries on the blueprint. The scripter emits
a single ``fn_callSupport.sqf`` function exposing an `addAction` menu entry
to each player. The calls respect per-asset cooldown and use-count limits so
they don't trivialise missions.

No BIS module graph is involved — we wire simple scripted variants that work
everywhere (vanilla, ACE, RHS) without hidden dependencies.
"""
from __future__ import annotations

from ..protocols import MissionBlueprint, SupportAsset

_CAS_TEMPLATE = '''\
    case "cas": {
        private _plane = createVehicle [_vehicle, _pos getPos [800, _heading - 180], [], 0, "FLY"];
        _plane flyInHeight 150;
        _plane setDir (_heading - 180);
        _plane setVelocity [sin _heading * 180, cos _heading * 180, 0];
        private _group = createVehicleCrew _plane;
        _group move _pos;
        // Strafe attack: fire at the target marker then RTB.
        [_plane, _pos, _ordnance] spawn {
            params ["_p", "_t", "_o"];
            waitUntil { (_p distance _t) < 600 || { !alive _p } };
            _p fire _o;
            sleep 2;
            deleteVehicle _p;
        };
        _plane
    };
'''

_ARTY_TEMPLATE = '''\
    case "artillery": {
        // Single fire mission: 5 HE shells on the target marker.
        private _rnds = [];
        for "_i" from 0 to 4 do {
            private _shell = createVehicle [_ordnance,
                _pos vectorAdd [random 40 - 20, random 40 - 20, 200], [], 0, "CAN_COLLIDE"];
            _shell setVelocity [0, 0, -80];
            _rnds pushBack _shell;
            sleep 1.5;
        };
        _rnds
    };
'''

_MEDEVAC_TEMPLATE = '''\
    case "medevac": {
        private _heli = createVehicle [_vehicle, _pos getPos [600, _heading - 180], [], 0, "FLY"];
        private _g = createVehicleCrew _heli;
        [_heli, _pos] spawn {
            params ["_h", "_t"];
            _h flyInHeight 50;
            _h doMove _t;
            waitUntil { (_h distance _t) < 60 || { !alive _h } };
            _h land "GET IN";
            waitUntil { (getPosATL _h) select 2 < 2 || { !alive _h } };
        };
        _heli
    };
'''

_TRANSPORT_TEMPLATE = '''\
    case "transport": {
        private _heli = createVehicle [_vehicle, _pos getPos [600, _heading - 180], [], 0, "FLY"];
        private _g = createVehicleCrew _heli;
        _heli flyInHeight 60;
        _heli doMove _pos;
        _heli
    };
'''

_AMMO_DROP_TEMPLATE = '''\
    case "ammo_drop": {
        private _crate = createVehicle [_ammo,
            _pos getPos [10, random 360], [], 0, "NONE"];
        [_crate] spawn {
            params ["_c"];
            _c allowDamage false;
            _c setPosATL [(getPosATL _c) select 0, (getPosATL _c) select 1, 200];
            _c setVelocity [0, 0, -10];
            private _p = createVehicle ["B_Parachute_02_F", getPosATL _c, [], 0, "NONE"];
            _p attachTo [_c, [0, 0, 0]];
            waitUntil { ((getPosATL _c) select 2) < 1 };
            detach _p;
            deleteVehicle _p;
        };
        _crate
    };
'''


_CASE_TEMPLATES = {
    "cas": _CAS_TEMPLATE,
    "artillery": _ARTY_TEMPLATE,
    "medevac": _MEDEVAC_TEMPLATE,
    "transport": _TRANSPORT_TEMPLATE,
    "ammo_drop": _AMMO_DROP_TEMPLATE,
}


def _fill_defaults(asset: SupportAsset) -> SupportAsset:
    """Pick sensible vanilla defaults when the designer left fields empty."""
    defaults = {
        "cas": {
            "vehicle_classname": "B_Plane_CAS_01_dynamicLoadout_F",
            "ordnance_classname": "Bo_GBU12_LGB",
        },
        "artillery": {"ordnance_classname": "Sh_82mm_AMOS"},
        "medevac": {"vehicle_classname": "B_Heli_Transport_01_F"},
        "transport": {"vehicle_classname": "B_Heli_Transport_01_F"},
        "ammo_drop": {"ammo_classname": "Box_NATO_Ammo_F"},
    }
    d = defaults.get(asset.kind, {})
    return asset.model_copy(update={
        k: getattr(asset, k) or v
        for k, v in d.items()
    })


def generate_support_sqf(blueprint: MissionBlueprint) -> str:
    """Return ``functions/fn_callSupport.sqf`` content."""
    if not blueprint.support_assets:
        return "// No support assets configured.\n"

    cases: list[str] = []
    for raw in blueprint.support_assets:
        asset = _fill_defaults(raw)
        template = _CASE_TEMPLATES.get(asset.kind)
        if template is None:
            continue
        cases.append(template)

    body = "\n".join(cases)
    return (
        "// fn_callSupport.sqf — dispatch a support request.\n"
        "// Called via the addAction bound in fn_registerSupportActions.sqf\n"
        "params [\n"
        "    [\"_kind\", \"\", [\"\"]],\n"
        "    [\"_pos\", [0,0,0], [[]]],\n"
        "    [\"_heading\", 0, [0]],\n"
        "    [\"_vehicle\", \"\", [\"\"]],\n"
        "    [\"_ordnance\", \"\", [\"\"]],\n"
        "    [\"_ammo\", \"\", [\"\"]]\n"
        "];\n"
        "if (!isServer) exitWith {\n"
        "    _this remoteExec [\"A3B_fnc_callSupport\", 2];\n"
        "};\n"
        "\n"
        "switch (toLower _kind) do {\n"
        + body +
        "\n    default { diag_log format [\"[A3B] Unknown support kind %1\", _kind]; };\n"
        "};\n"
    )


def generate_support_actions_sqf(blueprint: MissionBlueprint) -> str:
    """Client-local — add a menu entry per asset with cooldown enforcement."""
    if not blueprint.support_assets:
        return "// No support actions to register.\n"

    entries: list[str] = []
    for raw in blueprint.support_assets:
        asset = _fill_defaults(raw)
        cd = max(0, asset.cooldown_seconds)
        uses = max(0, asset.uses)
        args = (
            f'"{asset.kind}", getPosATL player, getDir player, '
            f'"{asset.vehicle_classname}", "{asset.ordnance_classname}", '
            f'"{asset.ammo_classname}"'
        )
        entries.append(
            f'_slot = "A3B_support_{asset.kind}";\n'
            f'player setVariable [_slot + "_uses", {uses if uses > 0 else 9999}];\n'
            f'player setVariable [_slot + "_next", 0];\n'
            f'player addAction [\n'
            f'    "<t color=\'#66ff66\'>Call {asset.name}</t>",\n'
            f'    {{ params ["_t", "_c"]; _kind = "{asset.kind}";\n'
            f'       _k = "A3B_support_{asset.kind}";\n'
            f'       _rem = _t getVariable [_k + "_uses", 0];\n'
            f'       _next = _t getVariable [_k + "_next", 0];\n'
            f'       if (_rem <= 0 || diag_tickTime < _next) exitWith {{\n'
            f'           hint format ["Support unavailable (%1 uses left, cd %2s)",\n'
            f'               _rem, round (_next - diag_tickTime)]; }};\n'
            f'       _t setVariable [_k + "_uses", _rem - 1];\n'
            f'       _t setVariable [_k + "_next", diag_tickTime + {cd}];\n'
            f'       [{args}] remoteExec ["A3B_fnc_callSupport", 2];\n'
            f'       hint "Support inbound!";\n'
            f'    }},\n'
            f'    nil, 1.5, true, true, "", "true", 50, false, "", ""\n'
            f'];'
        )

    return (
        "// fn_registerSupportActions.sqf — run on each client at start / JIP.\n"
        "if (!hasInterface) exitWith {};\n"
        "waitUntil { !isNull player };\n"
        "private _slot = \"\";\n"
        "private _rem = 0;\n"
        "private _next = 0;\n"
        "\n"
        + "\n".join(entries)
        + "\ntrue\n"
    )
