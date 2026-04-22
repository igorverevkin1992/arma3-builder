"""mission.sqm generation.

Two paths:
  1. If `armaclass` is installed, we serialise via its parser (typesafe round-trip).
  2. Otherwise we fall back to an internal writer that emits the modern
     Eden-Editor format (version 53) using the documented class hierarchy.

The internal writer is sufficient to load in 3D Editor for the cases the agent
pipeline produces (units + groups + waypoints + addons metadata).
"""
from __future__ import annotations

from typing import Any

from ..protocols import MissionBlueprint, UnitPlacement, Waypoint
from .classnames import ClassnameRegistry

SQM_VERSION = 53


def build_sqm_dict(blueprint: MissionBlueprint, registry: ClassnameRegistry) -> dict[str, Any]:
    """Build a structured dict that mirrors the SQM AST.

    This is the format consumed both by the Armaclass writer and by the
    internal fallback. Each top-level key matches an SQM root class.
    """
    addons = sorted({registry.addon_for(u.classname) for u in blueprint.units} | set(blueprint.addons))
    addons = [a for a in addons if a]
    items: list[dict[str, Any]] = []

    groups: dict[str, list[UnitPlacement]] = {}
    for u in blueprint.units:
        groups.setdefault(u.group_id, []).append(u)

    item_id = 0
    for group_id, units in groups.items():
        side = units[0].side
        wps = [w for w in blueprint.waypoints if w.group_id == group_id]
        items.append(_group_node(item_id, side, units, wps))
        item_id += 1

    return {
        "version": SQM_VERSION,
        "EditorData": {
            "moveGridStep": 1.0,
            "angleGridStep": 0.2617994,
            "scaleGridStep": 1.0,
            "autoGroupingDist": 10.0,
            "toggles": 1,
        },
        "binarizationWanted": 0,
        "sourceName": blueprint.brief.title,
        "addons": addons,
        "AddonsMetaData": _addons_metadata(addons),
        "ScenarioData": {
            "author": "arma3-builder",
            "overviewText": blueprint.brief.summary,
        },
        "Mission": {
            "Intel": {
                "timeOfChanges": 1.0,
                "startWeather": 0.3 if blueprint.brief.weather == "clear" else 0.7,
                "startWind": 0.1,
                "startWaves": 0.1,
                "forecastWeather": 0.3,
                "year": 2035,
                "month": 6,
                "day": 24,
                "hour": int(blueprint.brief.time_of_day.split(":")[0]),
                "minute": int(blueprint.brief.time_of_day.split(":")[1]) if ":" in blueprint.brief.time_of_day else 0,
            },
            "Entities": {"items": items},
        },
    }


def _addons_metadata(addons: list[str]) -> dict[str, Any]:
    return {
        "List": [{"className": a, "name": a} for a in addons],
    }


def _group_node(idx: int, side: str, units: list[UnitPlacement], waypoints: list[Waypoint]) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    for i, u in enumerate(units):
        entities.append({
            "dataType": "Object",
            "id": idx * 1000 + i + 1,
            "side": side,
            "Attributes": {
                "name": u.name or f"unit_{idx}_{i}",
                "isPlayer": int(u.is_player),
                "isLeader": int(u.is_leader or i == 0),
            },
            "PositionInfo": {
                "position": list(u.position),
                "angleY": u.direction,
            },
            "type": u.classname,
        })
    for j, w in enumerate(waypoints):
        entities.append({
            "dataType": "Waypoint",
            "id": idx * 1000 + 500 + j,
            "PositionInfo": {"position": list(w.position)},
            "type": w.type,
            "behaviour": w.behaviour,
            "speed": w.speed,
        })
    return {
        "dataType": "Group",
        "id": 10_000 + idx,
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
    """Minimal but valid Eden-format SQM emitter.

    Produces a `version=53;` header followed by class blocks. This is a
    deterministic deep traversal: scalars become `key=value;`, dicts become
    nested `class key { ... };` blocks, and lists become indexed or array
    literals depending on element type.
    """
    pad = "    " * indent
    out: list[str] = []
    items_array_keys = {"items", "List"}

    for key, value in sqm.items():
        if isinstance(value, dict):
            out.append(f"{pad}class {key}\n{pad}{{")
            out.append(_internal_render(value, indent + 1))
            out.append(f"{pad}}};")
        elif isinstance(value, list) and key in items_array_keys:
            for i, entry in enumerate(value):
                if isinstance(entry, dict):
                    out.append(f"{pad}class Item{i}\n{pad}{{")
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
        return repr(v)
    if isinstance(v, str):
        escaped = v.replace('"', '""')
        return f'"{escaped}"'
    if v is None:
        return '""'
    return f'"{str(v)}"'
