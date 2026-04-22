"""Parse mod `config.cpp` files into the classname index.

This is a pragmatic config parser: it walks `class Name : Parent { ... };`
blocks and pulls out a small set of declarative attributes
(`scope`, `displayName`, `side`, `faction`, `type`...). It is NOT a full
preprocessor — but covers ~95% of vanilla and RHS/CUP/ACE configs.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from .store import Document, VectorStore


@dataclass
class ClassNode:
    name: str
    parent: str
    body: str
    attrs: dict[str, str]


_CLASS_HEADER_RE = re.compile(
    r"\bclass\s+([A-Za-z_][\w]*)\s*(?::\s*([A-Za-z_][\w]*))?\s*\{",
)
_KV_RE = re.compile(r"\b([A-Za-z_][\w]*)\s*=\s*\"([^\"]*)\"\s*;")
_NUM_KV_RE = re.compile(r"\b([A-Za-z_][\w]*)\s*=\s*(-?\d+)\s*;")


def parse_config_cpp(text: str) -> list[ClassNode]:
    """Pull class blocks out of a config.cpp.

    Brace-aware: walks the text recursively, matching balanced `{}` blocks per
    class header. Nested classes are returned alongside their parents so we
    can index leaf entities (vehicles, units) regardless of the wrapping
    `CfgVehicles` / `CfgWeapons` envelope.
    """
    nodes: list[ClassNode] = []
    _walk(text, 0, len(text), nodes)
    return nodes


def _walk(text: str, start: int, end: int, out: list[ClassNode]) -> None:
    i = start
    while i < end:
        m = _CLASS_HEADER_RE.search(text, i, end)
        if not m:
            return
        name, parent = m.group(1), (m.group(2) or "")
        depth = 1
        j = m.end()
        while j < end and depth > 0:
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            j += 1
        body = text[m.end(): j - 1]
        attrs: dict[str, str] = {}
        for km in _KV_RE.finditer(body):
            attrs[km.group(1)] = km.group(2)
        for km in _NUM_KV_RE.finditer(body):
            attrs.setdefault(km.group(1), km.group(2))
        out.append(ClassNode(name=name, parent=parent, body=body, attrs=attrs))
        # Recurse into the body — captures nested classes.
        _walk(text, m.end(), j - 1, out)
        i = j


_SIDE_LOOKUP = {"0": "EAST", "1": "WEST", "2": "INDEPENDENT", "3": "CIVILIAN"}


def classnode_to_document(node: ClassNode, *, tenant: str) -> Document:
    side_raw = node.attrs.get("side", "")
    side = _SIDE_LOOKUP.get(side_raw, side_raw)
    type_ = "Vehicle"
    if any(k in node.body for k in ["isMan = 1", "isMan=1"]):
        type_ = "Man"
    elif "Weapon" in node.parent:
        type_ = "Weapon"
    elif "Magazine" in node.parent:
        type_ = "Magazine"
    text = (
        f"Classname: {node.name}\n"
        f"Display: {node.attrs.get('displayName', node.name)}\n"
        f"Parent: {node.parent}\n"
        f"Side: {side}\n"
        f"Faction: {node.attrs.get('faction','')}\n"
        f"Type: {type_}\n"
        f"Tenant: {tenant}\n"
    )
    return Document(
        id=uuid.uuid4().hex,
        text=text,
        metadata={
            "source": "classnames",
            "tenant": tenant,
            "classname": node.name,
            "type": type_,
            "side": side,
            "faction": node.attrs.get("faction", ""),
            "displayName": node.attrs.get("displayName", node.name),
        },
    )


def ingest_config_cpp(store: VectorStore, path: Path, *, tenant: str) -> int:
    text = path.read_text(encoding="utf-8", errors="ignore")
    nodes = parse_config_cpp(text)
    docs = [classnode_to_document(n, tenant=tenant) for n in nodes if n.name]
    store.upsert(docs)
    return len(docs)
