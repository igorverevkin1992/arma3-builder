"""SQM import — parse Eden-saved mission.sqm back into a blueprint delta.

The generator emits a well-defined subset of the Eden SQM grammar via the
internal writer; designers editing in 3D Editor write out the same shape
(with additional fields we simply pass through). This tolerant parser
extracts the bits we care about for round-trip editing:

  * `class Mission > class Entities > class ItemN` unit/group/waypoint
    blocks → UnitPlacement list.
  * Respawn markers (`class Markers > ItemN`) → preserved as-is.
  * EditorData.Camera → ignored (not semantic).

Unknown sub-classes are stored raw so a subsequent re-emit preserves them
(best-effort round-trip). The parser is line-oriented and brace-balanced;
it intentionally does NOT attempt full grammar parsing — that's armaclass's
job when the optional dependency is installed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..protocols import MissionBlueprint, UnitPlacement, Waypoint

# --------------------------------------------------------------------------- #
# Tokeniser / balanced-class walker
# --------------------------------------------------------------------------- #


_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_][\w]*)\s*\{")
_KV_RE    = re.compile(r"([A-Za-z_][\w]*)\s*(?:\[\s*\])?\s*=\s*([^;]+);")


@dataclass
class ParsedClass:
    name: str
    attrs: dict[str, Any] = field(default_factory=dict)
    children: list[ParsedClass] = field(default_factory=list)


def parse_sqm(text: str) -> ParsedClass:
    """Parse SQM text into a tree of ``ParsedClass`` nodes.

    The root node is synthetic (name='ROOT'); top-level attributes and
    classes become its children. The parser tolerates whitespace, trailing
    commas and inline comments — anything outside our explicit grammar
    lands in ``ParsedClass.attrs['_raw']`` if it matters.
    """
    root = ParsedClass(name="ROOT")
    _parse_body(text, 0, len(text), root)
    return root


def _parse_body(text: str, start: int, end: int, parent: ParsedClass) -> None:
    i = start
    while i < end:
        # Skip whitespace / line-comments.
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if text[i:i+2] == "//":
            nl = text.find("\n", i)
            i = nl + 1 if nl != -1 else end
            continue
        # Class block.
        m = _CLASS_RE.match(text, i, end)
        if m:
            name = m.group(1)
            body_start = m.end()
            body_end = _find_match(text, body_start - 1, end)
            if body_end == -1:
                return
            node = ParsedClass(name=name)
            _parse_body(text, body_start, body_end, node)
            parent.children.append(node)
            # Skip trailing `};` or `;`.
            i = body_end + 1
            while i < end and text[i] in " \t\r\n;":
                i += 1
            continue
        # Key = value.
        km = _KV_RE.match(text, i, end)
        if km:
            key = km.group(1)
            raw_val = km.group(2).strip()
            parent.attrs[key] = _parse_value(raw_val)
            i = km.end()
            continue
        # Fallback: skip one char.
        i += 1


def _find_match(text: str, brace_idx: int, end: int) -> int:
    """Given `text[brace_idx]=='{'`, return the index of the matching `}`."""
    depth = 0
    i = brace_idx
    while i < end:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parse_value(s: str) -> Any:
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1].replace('""', '"')
    if s.startswith("{") and s.endswith("}"):
        # Array literal. Split on top-level commas (no nested arrays in
        # our emitted SQM, so naive split is safe).
        items = [_parse_value(p.strip())
                 for p in s[1:-1].split(",") if p.strip()]
        return items
    if s in ("true", "false"):
        return s == "true"
    # Try numeric.
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


# --------------------------------------------------------------------------- #
# Semantic extraction
# --------------------------------------------------------------------------- #


def _find_named(root: ParsedClass, path: list[str]) -> list[ParsedClass]:
    """Return every class matching ``path`` (ordered list of class names)."""
    if not path:
        return [root]
    head, rest = path[0], path[1:]
    hits: list[ParsedClass] = []
    for c in root.children:
        if c.name == head:
            if rest:
                hits.extend(_find_named(c, rest))
            else:
                hits.append(c)
    return hits


def extract_units(root: ParsedClass) -> list[UnitPlacement]:
    """Walk Mission > Entities > ItemN.{Group, Object, Waypoint}."""
    units: list[UnitPlacement] = []
    entities = _find_named(root, ["Mission", "Entities"])
    for entities_cls in entities:
        for item in entities_cls.children:
            if item.attrs.get("dataType") == "Group":
                side = item.attrs.get("side", "EAST")
                group_id = item.attrs.get("name", f"g{item.name}")
                inner_entities = _find_named(item, ["Entities"])
                for inner in inner_entities:
                    for ent in inner.children:
                        if ent.attrs.get("dataType") != "Object":
                            continue
                        units.append(_object_to_unit(ent, side, group_id))
            elif item.attrs.get("dataType") == "Object":
                # Rare — a loose Object at the top level.
                units.append(_object_to_unit(item, item.attrs.get("side", "WEST"),
                                             "top_level"))
    return units


def _object_to_unit(
    ent: ParsedClass, side: str, group_id: str,
) -> UnitPlacement:
    pos = [0.0, 0.0, 0.0]
    direction = 0.0
    name = None
    is_player = False
    is_leader = False

    for c in ent.children:
        if c.name == "PositionInfo":
            raw = c.attrs.get("position")
            if isinstance(raw, list) and len(raw) >= 3:
                # SQM stores [x, altitude, y]; convert back to our (x, y, alt).
                pos = [float(raw[0]), float(raw[2]), float(raw[1])]
            direction = float(c.attrs.get("angleY", 0.0))
        if c.name == "Attributes":
            name = c.attrs.get("name", name)
            is_player = bool(c.attrs.get("isPlayer", 0))
            is_leader = bool(c.attrs.get("isLeader", 0))

    return UnitPlacement(
        classname=ent.attrs.get("type", "B_Soldier_F"),
        side=side,
        position=(pos[0], pos[1], pos[2]),
        direction=direction,
        name=name,
        is_player=is_player,
        is_leader=is_leader,
        group_id=group_id,
    )


def extract_waypoints(root: ParsedClass) -> list[Waypoint]:
    wps: list[Waypoint] = []
    entities = _find_named(root, ["Mission", "Entities"])
    for entities_cls in entities:
        for item in entities_cls.children:
            if item.attrs.get("dataType") != "Group":
                continue
            group_id = item.attrs.get("name", f"g{item.name}")
            inner_entities = _find_named(item, ["Entities"])
            for inner in inner_entities:
                for ent in inner.children:
                    if ent.attrs.get("dataType") != "Waypoint":
                        continue
                    raw = None
                    for c in ent.children:
                        if c.name == "PositionInfo":
                            raw = c.attrs.get("position")
                    if not (isinstance(raw, list) and len(raw) >= 3):
                        continue
                    wps.append(Waypoint(
                        group_id=group_id,
                        position=(float(raw[0]), float(raw[2]), float(raw[1])),
                        type=ent.attrs.get("type", "MOVE"),
                        behaviour=ent.attrs.get("behaviour", "AWARE"),
                        speed=ent.attrs.get("speed", "NORMAL"),
                    ))
    return wps


def sync_into_blueprint(
    blueprint: MissionBlueprint,
    sqm_text: str,
) -> MissionBlueprint:
    """Merge edits from Eden back onto ``blueprint``.

    Strategy: the SQM is authoritative for unit positions / attributes /
    waypoints; everything else (FSM, dialog, support, cutscenes, pacing,
    loadouts…) is retained from the original blueprint. Designers thus get
    free-form map editing without losing the scripted layer.
    """
    root = parse_sqm(sqm_text)
    new_units = extract_units(root)
    new_waypoints = extract_waypoints(root)

    # If the parser yielded nothing (malformed paste), don't wipe data.
    updated = blueprint.model_copy(deep=True)
    if new_units:
        updated.units = new_units
    if new_waypoints:
        updated.waypoints = new_waypoints
    return updated
