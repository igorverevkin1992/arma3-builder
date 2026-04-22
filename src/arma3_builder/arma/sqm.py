"""mission.sqm generation.

Produces an Eden-Editor compatible mission.sqm (format version 53). Includes
all mandatory top-level classes that modern 3D editor expects:

  * EditorData { Camera { … }; moveGridStep = …; }
  * ItemIDProvider / MarkerIDProvider / LayerIndexProvider
  * Connections
  * Mission { Intel, Entities, Markers, Groups }
  * AddonsMetaData (required for mod-aware loading)

Two rendering paths:
  1. If `armaclass` is installed, serialise via its parser.
  2. Otherwise internal deterministic writer (default).
"""
from __future__ import annotations

from typing import Any

from ..protocols import MissionBlueprint, UnitPlacement, Waypoint
from .classnames import ClassnameRegistry

SQM_VERSION = 53

_SIDE_TO_RESPAWN = {
    "WEST": "respawn_west",
    "EAST": "respawn_east",
    "INDEPENDENT": "respawn_guerrila",
    "CIVILIAN": "respawn_civilian",
}


def build_sqm_dict(
    blueprint: MissionBlueprint,
    registry: ClassnameRegistry,
    *,
    include_respawn_markers: bool = True,
) -> dict[str, Any]:
    """Build a structured dict mirroring the SQM AST."""
    addons = sorted(
        {registry.addon_for(u.classname) for u in blueprint.units} | set(blueprint.addons)
    )
    addons = [a for a in addons if a]

    # Always include the base a3_map package and editable category.
    if "A3_Characters_F" not in addons and any(
        registry.items.get(u.classname) and registry.items[u.classname].type == "Man"
        for u in blueprint.units
    ):
        addons.append("A3_Characters_F")

    # Counters for id uniqueness across the whole mission.
    id_counter = _IdCounter(start=100)

    items: list[dict[str, Any]] = []

    # 1. Groups & units
    groups: dict[str, list[UnitPlacement]] = {}
    for u in blueprint.units:
        groups.setdefault(u.group_id, []).append(u)

    for group_id, units in groups.items():
        side = units[0].side
        wps = [w for w in blueprint.waypoints if w.group_id == group_id]
        items.append(_group_node(id_counter, side, units, wps))

    # 2. Respawn markers (required for respawn="BASE")
    markers: list[dict[str, Any]] = []
    if include_respawn_markers:
        sides_needing = {u.side for u in blueprint.units if u.is_player}
        for side in sides_needing:
            marker_name = _SIDE_TO_RESPAWN.get(side)
            if not marker_name:
                continue
            # Place marker 20 m away from the first player so it's not under them.
            base_pos = next(
                (u.position for u in blueprint.units if u.is_player and u.side == side),
                (0.0, 0.0, 0.0),
            )
            markers.append({
                "dataType": "Marker",
                "id": id_counter.next(),
                "position": [base_pos[0] + 20.0, base_pos[1] + 20.0, 0.0],
                "name": marker_name,
                "markerType": "ELLIPSE",
                "type": "Empty",
                "a": 5.0,
                "b": 5.0,
                "drawBorder": 1,
                "colorName": "ColorBlue" if side == "WEST" else "ColorRed",
            })

    return {
        "version": SQM_VERSION,
        "EditorData": {
            "moveGridStep": 1.0,
            "angleGridStep": 0.2617994,
            "scaleGridStep": 1.0,
            "autoGroupingDist": 10.0,
            "toggles": 1,
            "Camera": {
                "pos": [
                    (blueprint.units[0].position[0] if blueprint.units else 0.0) - 50.0,
                    (blueprint.units[0].position[2] if blueprint.units else 0.0) + 40.0,
                    (blueprint.units[0].position[1] if blueprint.units else 0.0) - 50.0,
                ],
                "dir": [0.0, -0.5, 0.87],
                "up": [0.0, 0.87, 0.5],
                "aside": [1.0, 0.0, 0.0],
            },
        },
        "binarizationWanted": 0,
        "sourceName": blueprint.brief.title,
        "addons": addons,
        "AddonsMetaData": {"List": [{"className": a, "name": a} for a in addons]},
        "randomSeed": 12345,
        "ScenarioData": {
            "author": "arma3-builder",
            "overviewText": blueprint.brief.summary,
        },
        "CustomAttributes": {"version": 1},
        "ItemIDProvider": {"nextID": id_counter.peek()},
        "MarkerIDProvider": {"nextID": max(1, len(markers))},
        "LayerIndexProvider": {"nextID": 1},
        "Connections": {"ItemIDProvider": {"nextID": 1}},
        "Mission": {
            "Intel": _intel(blueprint),
            "Entities": {"items": items},
            "Markers": {"items": markers} if markers else None,
        },
    }


class _IdCounter:
    def __init__(self, *, start: int) -> None:
        self._v = start

    def next(self) -> int:
        v = self._v
        self._v += 1
        return v

    def peek(self) -> int:
        return self._v


def _intel(blueprint: MissionBlueprint) -> dict[str, Any]:
    hour, _, minute = blueprint.brief.time_of_day.partition(":")
    try:
        h = int(hour)
    except ValueError:
        h = 12
    try:
        m = int(minute or 0)
    except ValueError:
        m = 0
    weather_map = {"clear": 0.2, "overcast": 0.5, "rain": 0.8, "storm": 1.0}
    w = weather_map.get(blueprint.brief.weather, 0.3)
    return {
        "timeOfChanges": 1800.0,
        "startWeather": w,
        "startWind": 0.1,
        "startWaves": 0.1,
        "forecastWeather": w,
        "forecastWind": 0.1,
        "forecastWaves": 0.1,
        "forecastLightnings": 0.0,
        "year": 2035,
        "month": 6,
        "day": 24,
        "hour": h,
        "minute": m,
    }


def _group_node(
    ids: _IdCounter,
    side: str,
    units: list[UnitPlacement],
    waypoints: list[Waypoint],
) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    for i, u in enumerate(units):
        is_leader = 1 if (u.is_leader or i == 0) else 0
        entities.append({
            "dataType": "Object",
            "id": ids.next(),
            "side": side,
            "Attributes": {
                "name": u.name or f"unit_{i}",
                "isPlayer": 1 if u.is_player else 0,
                "isLeader": is_leader,
                "skill": 0.6,
                "description": u.name or "",
            },
            "PositionInfo": {
                "position": [u.position[0], u.position[2], u.position[1]],
                "angleY": u.direction,
            },
            "type": u.classname,
            "flags": 6 if u.is_player else 4,
        })
    for w in waypoints:
        entities.append({
            "dataType": "Waypoint",
            "id": ids.next(),
            "PositionInfo": {"position": [w.position[0], w.position[2], w.position[1]]},
            "type": w.type,
            "behaviour": w.behaviour,
            "speed": w.speed,
            "combatMode": "YELLOW",
            "formation": "WEDGE",
        })
    return {
        "dataType": "Group",
        "id": ids.next(),
        "side": side,
        "Entities": {"items": entities},
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_sqm(sqm: dict[str, Any]) -> str:
    """Emit the SQM dict as text.

    Tries armaclass first; otherwise falls back to the internal writer.
    """
    try:
        import armaclass  # type: ignore[import-not-found]

        if hasattr(armaclass, "dumps"):
            return armaclass.dumps(sqm)  # type: ignore[no-any-return]
    except ImportError:
        pass
    return _internal_render(sqm)


def _internal_render(sqm: dict[str, Any], indent: int = 0) -> str:
    """Deterministic Eden-format SQM emitter."""
    pad = "    " * indent
    out: list[str] = []
    items_array_keys = {"items", "List"}

    for key, value in sqm.items():
        if value is None:
            continue
        if isinstance(value, dict):
            out.append(f"{pad}class {key}")
            out.append(f"{pad}{{")
            out.append(_internal_render(value, indent + 1))
            out.append(f"{pad}}};")
        elif isinstance(value, list) and key in items_array_keys:
            for i, entry in enumerate(value):
                if isinstance(entry, dict):
                    out.append(f"{pad}class Item{i}")
                    out.append(f"{pad}{{")
                    out.append(_internal_render(entry, indent + 1))
                    out.append(f"{pad}}};")
                else:
                    out.append(f'{pad}item{i} = {_render_scalar(entry)};')
        elif isinstance(value, list):
            inner = ",".join(_render_scalar(v) for v in value)
            out.append(f"{pad}{key}[] = {{{inner}}};")
        else:
            out.append(f"{pad}{key} = {_render_scalar(value)};")
    return "\n".join(out)


def _render_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v.is_integer():
            return repr(v)
        return repr(v)
    if isinstance(v, str):
        escaped = v.replace('"', '""')
        return f'"{escaped}"'
    if v is None:
        return '""'
    return f'"{str(v)}"'
