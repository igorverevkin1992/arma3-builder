"""Composition expansion — turn a named squad template into real units.

The Narrative Director can declare a composition instead of hand-placing
every unit: ``Composition(kind="fire_team", side="EAST", anchor=(1000,2000,0))``
yields a TL + AR + AT + rifleman with walk-ready positions. Config Master
merges the resulting ``UnitPlacement``s into the blueprint's unit list
before handing off to SQM generation.

Keeping compositions in code (not JSON) means they can be parametric —
a squad of 8 vs a squad of 12 shares the same schema.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from ..protocols import Composition, UnitPlacement, Waypoint


@dataclass
class _Slot:
    role: str
    classname_hint: str                    # "rifleman" | "autorifleman" | "crew" | "driver"
    offset: tuple[float, float, float]


# Faction × role → classname lookup. Mirrors the loadout catalogue.
_CLASSNAMES: dict[tuple[str, str], str] = {
    ("vanilla", "EAST", "rifleman"):     "O_Soldier_F",
    ("vanilla", "EAST", "autorifleman"): "O_Soldier_AR_F",
    ("vanilla", "EAST", "leader"):       "O_Soldier_TL_F",
    ("vanilla", "EAST", "at"):           "O_Soldier_AT_F",
    ("vanilla", "EAST", "medic"):        "O_medic_F",
    ("vanilla", "EAST", "crew"):         "O_crew_F",
    ("vanilla", "WEST", "rifleman"):     "B_Soldier_F",
    ("vanilla", "WEST", "autorifleman"): "B_Soldier_AR_F",
    ("vanilla", "WEST", "leader"):       "B_Soldier_TL_F",
    ("vanilla", "WEST", "at"):           "B_Soldier_AT_F",
    ("vanilla", "WEST", "medic"):        "B_medic_F",
    ("vanilla", "WEST", "crew"):         "B_crew_F",
    ("rhsusf_main", "WEST", "rifleman"):     "rhsusf_socom_marsoc_marksman",
    ("rhsusf_main", "WEST", "autorifleman"): "rhsusf_socom_marsoc_sarc",
    ("rhsusf_main", "WEST", "leader"):       "rhsusf_socom_marsoc_teamleader",
    ("rhsusf_main", "WEST", "breacher"):     "rhsusf_socom_marsoc_breacher",
}


def _classname(faction: str, side: str, role: str) -> str:
    return (
        _CLASSNAMES.get((faction, side, role))
        or _CLASSNAMES.get(("vanilla", side, role))
        or _CLASSNAMES.get(("vanilla", side, "rifleman"), "B_Soldier_F")
    )


# --------------------------------------------------------------------------- #
# Slot layouts per composition kind
# --------------------------------------------------------------------------- #


def _fire_team() -> list[_Slot]:
    return [
        _Slot("team_leader",  "leader",      (0.0, 0.0, 0.0)),
        _Slot("autorifleman", "autorifleman",(3.0, 2.0, 0.0)),
        _Slot("at",           "at",          (-3.0, 2.0, 0.0)),
        _Slot("rifleman",     "rifleman",    (0.0, 4.0, 0.0)),
    ]


def _squad() -> list[_Slot]:
    return _fire_team() + [
        _Slot("rifleman_2",   "rifleman",    (4.0, 6.0, 0.0)),
        _Slot("rifleman_3",   "rifleman",    (-4.0, 6.0, 0.0)),
        _Slot("medic",        "medic",       (0.0, 8.0, 0.0)),
        _Slot("rifleman_4",   "rifleman",    (2.0, 10.0, 0.0)),
    ]


def _motorised_patrol() -> list[_Slot]:
    # Vehicle + crew. The vehicle classname is the "leader" of the group
    # so the SQM/AI handles crew-of-vehicle semantics automatically.
    return [
        _Slot("driver",   "crew",     (0.0, 0.0, 0.0)),
        _Slot("gunner",   "crew",     (1.0, 0.0, 0.0)),
        _Slot("commander","leader",   (2.0, 0.0, 0.0)),
    ]


def _garrison(size: int) -> list[_Slot]:
    """Place ``size`` riflemen in a rough circle around the anchor."""
    return [
        _Slot(
            f"guard_{i}", "rifleman",
            (math.cos(i * math.tau / size) * 8.0,
             math.sin(i * math.tau / size) * 8.0,
             0.0),
        )
        for i in range(max(1, size))
    ]


def _vip_convoy() -> list[_Slot]:
    return [
        _Slot("escort_lead_driver",  "crew",     (-8.0, 0.0, 0.0)),
        _Slot("escort_lead_gunner",  "crew",     (-8.0, 1.5, 0.0)),
        _Slot("vip",                 "leader",   (0.0, 0.0, 0.0)),
        _Slot("vip_driver",          "crew",     (0.0, 1.5, 0.0)),
        _Slot("escort_rear_driver",  "crew",     (8.0, 0.0, 0.0)),
        _Slot("escort_rear_gunner",  "crew",     (8.0, 1.5, 0.0)),
    ]


def _heli_insertion() -> list[_Slot]:
    # Compact 6-man team for heli-drop.
    return [
        _Slot("team_leader",  "leader",     (0.0, 0.0, 0.0)),
        _Slot("breacher",     "rifleman",   (1.5, 0.0, 0.0)),
        _Slot("autorifleman", "autorifleman", (3.0, 0.0, 0.0)),
        _Slot("medic",        "medic",      (-1.5, 0.0, 0.0)),
        _Slot("rifleman_1",   "rifleman",   (-3.0, 0.0, 0.0)),
        _Slot("rifleman_2",   "rifleman",   (0.0, 2.0, 0.0)),
    ]


_LAYOUTS: dict[str, Callable[[int], list[_Slot]]] = {
    "fire_team":        lambda size: _fire_team(),
    "squad":            lambda size: _squad(),
    "motorised_patrol": lambda size: _motorised_patrol(),
    "vip_convoy":       lambda size: _vip_convoy(),
    "garrison":         _garrison,
    "heli_insertion":   lambda size: _heli_insertion(),
}


def expand_composition(
    comp: Composition,
) -> tuple[list[UnitPlacement], list[Waypoint]]:
    """Return (units, waypoints) materialised from the composition.

    Waypoints are a short patrol loop around the anchor for land squads,
    empty for convoys and garrisons.
    """
    layout_fn = _LAYOUTS.get(comp.kind)
    if layout_fn is None:
        return [], []
    slots = layout_fn(max(1, comp.size))
    cos_a = math.cos(math.radians(comp.heading))
    sin_a = math.sin(math.radians(comp.heading))

    units: list[UnitPlacement] = []
    group_id = comp.group_id or comp.id
    for i, slot in enumerate(slots):
        # Rotate offset by heading, then translate to anchor.
        ox, oy, oz = slot.offset
        dx = ox * cos_a - oy * sin_a
        dy = ox * sin_a + oy * cos_a
        pos = (comp.anchor[0] + dx, comp.anchor[1] + dy, comp.anchor[2] + oz)
        classname = _classname(comp.faction_hint, comp.side, slot.classname_hint)
        units.append(UnitPlacement(
            classname=classname,
            side=comp.side,
            position=pos,
            direction=comp.heading,
            name=f"{comp.id}_{slot.role}",
            is_leader=(i == 0),
            group_id=group_id,
        ))

    waypoints: list[Waypoint] = []
    if comp.kind in {"fire_team", "squad", "heli_insertion"}:
        # Simple 4-point patrol loop 40 m around the anchor, behaviour AWARE.
        for i in range(4):
            ax = math.cos(i * math.tau / 4) * 40.0
            ay = math.sin(i * math.tau / 4) * 40.0
            waypoints.append(Waypoint(
                group_id=group_id,
                position=(comp.anchor[0] + ax, comp.anchor[1] + ay, comp.anchor[2]),
                type="MOVE", behaviour="AWARE", speed="NORMAL",
            ))
    return units, waypoints


def expand_all(comps: list[Composition]) -> tuple[list[UnitPlacement], list[Waypoint]]:
    units: list[UnitPlacement] = []
    waypoints: list[Waypoint] = []
    for c in comps:
        u, w = expand_composition(c)
        units.extend(u)
        waypoints.extend(w)
    return units, waypoints
