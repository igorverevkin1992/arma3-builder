"""Ingest Biki wiki dumps (markdown / wikitext) into the RAG store."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from .chunking import semantic_chunks, table_to_markdown
from .store import Document, VectorStore


_HTML_TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)


def _normalise(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return "\n" + table_to_markdown(match.group(0)) + "\n"
    return _HTML_TABLE_RE.sub(repl, text)


def ingest_directory(store: VectorStore, directory: Path, *, source: str = "biki") -> int:
    """Walk a directory of `.md` / `.txt` files and feed them into the store.

    Each file produces one or more chunks (one per semantic section).
    Returns the number of chunks indexed.
    """
    count = 0
    docs: list[Document] = []
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() not in {".md", ".txt", ".wiki"}:
            continue
        body = _normalise(path.read_text(encoding="utf-8", errors="ignore"))
        base_meta = {
            "source": source,
            "path": str(path.relative_to(directory)),
            "title": path.stem,
        }
        for chunk in semantic_chunks(body, base_metadata=base_meta):
            docs.append(Document(
                id=uuid.uuid4().hex,
                text=f"# {chunk.title}\n\n{chunk.body}",
                metadata={**chunk.metadata, "title": chunk.title},
            ))
            count += 1
    store.upsert(docs)
    return count


def ingest_jsonl(store: VectorStore, path: Path, *, source: str = "biki") -> int:
    """Ingest a JSONL where every line is `{ "title": ..., "body": ..., ... }`."""
    docs: list[Document] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            meta = {**entry, "source": source}
            meta.pop("body", None)
            docs.append(Document(
                id=uuid.uuid4().hex,
                text=f"# {entry.get('title','?')}\n\n{entry.get('body','')}",
                metadata=meta,
            ))
    store.upsert(docs)
    return len(docs)
