"""Semantic chunking helpers for the RAG ingestion pipeline.

The Biki wiki is structured around command pages with a fixed sub-section
layout (Syntax / Parameters / Return value / Examples). Naive fixed-window
splitting destroys this structure; we slice along the heading boundaries so
each chunk inherits the full description of one command.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Chunk:
    title: str
    body: str
    metadata: dict


def semantic_chunks(
    text: str,
    *,
    base_metadata: dict | None = None,
    min_chars: int = 80,
    max_chars: int = 4000,
) -> list[Chunk]:
    """Split a markdown/wiki document along headings, preserving sections."""
    base = dict(base_metadata or {})
    sections: list[tuple[str, str]] = []

    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [Chunk(title=base.get("title", "doc"), body=text.strip(), metadata=base)]

    matches.append(None)  # type: ignore[arg-type]
    for i, m in enumerate(matches[:-1]):
        nxt = matches[i + 1]
        title = m.group(2).strip()
        start = m.end()
        end = nxt.start() if nxt is not None else len(text)
        body = text[start:end].strip()
        if len(body) < min_chars:
            continue
        sections.append((title, body[:max_chars]))

    return [
        Chunk(title=t, body=b, metadata={**base, "section": t})
        for t, b in sections
    ]


_TABLE_LINE_RE = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)


def table_to_markdown(html_or_wiki_table: str) -> str:
    """Convert a simple HTML/wiki table to markdown.

    Real-world Biki tables vary; this helper normalises only the common
    `| col | col |` shape, leaving HTML tables intact for downstream tools.
    """
    lines = [line.strip() for line in html_or_wiki_table.splitlines() if line.strip()]
    rows: list[list[str]] = []
    for line in lines:
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append(cells)
    if not rows:
        return html_or_wiki_table
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(r) + " |" for r in rows]
    out.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(out)
