"""Populate the RAG store from local seed data so agents can query immediately.

Called lazily the first time `get_retriever()` is used. Idempotent: re-indexing
the same seed files is a no-op because `MemoryStore` upserts by id.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from ..config import data_dir
from .ingest_biki import ingest_directory
from .ingest_classnames import classnode_to_document
from .store import Document, VectorStore


def _seed_classnames(store: VectorStore) -> int:
    directory = data_dir() / "seed_classnames"
    if not directory.exists():
        return 0
    docs: list[Document] = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        tenant = data.get("tenant", path.stem)
        for entry in data.get("classnames", []):
            meta = {
                "source": "classnames",
                "tenant": tenant,
                "classname": entry["classname"],
                "addon": entry["addon"],
                "type": entry.get("type", "Object"),
                "faction": entry.get("faction", ""),
                "side": entry.get("side", ""),
                "displayName": entry.get("display_name", entry["classname"]),
            }
            text = (
                f"Classname: {entry['classname']}\n"
                f"Addon: {entry['addon']}\n"
                f"Side: {meta['side']}\n"
                f"Faction: {meta['faction']}\n"
                f"Type: {meta['type']}\n"
                f"Tenant: {tenant}\n"
            )
            docs.append(Document(id=uuid.uuid4().hex, text=text, metadata=meta))
    store.upsert(docs)
    return len(docs)


def _seed_biki(store: VectorStore) -> int:
    directory = data_dir() / "seed_biki"
    if not directory.exists():
        return 0
    return ingest_directory(store, directory, source="biki")


def bootstrap(store: VectorStore) -> dict[str, int]:
    if store.count() > 0:
        return {"skipped": store.count()}
    return {
        "classnames": _seed_classnames(store),
        "biki": _seed_biki(store),
    }
