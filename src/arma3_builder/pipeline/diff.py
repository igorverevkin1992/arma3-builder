"""Unified-diff generator between two generation runs.

Designers use this to see exactly what changed after a follow-up prompt
("make mission 2 night" → diff of SQF/SQM per file).
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from ..protocols import GeneratedArtifact


@dataclass
class ArtifactDiff:
    path: str
    change: str                   # "added" | "removed" | "modified" | "unchanged"
    unified: str = ""


def diff_artifacts(
    before: list[GeneratedArtifact],
    after: list[GeneratedArtifact],
) -> list[ArtifactDiff]:
    b_by_path = {a.relative_path: a for a in before}
    a_by_path = {a.relative_path: a for a in after}
    paths = sorted(set(b_by_path) | set(a_by_path))
    out: list[ArtifactDiff] = []
    for path in paths:
        b = b_by_path.get(path)
        a = a_by_path.get(path)
        if b is None:
            out.append(ArtifactDiff(path=path, change="added",
                                    unified=_unified("", a.content, path)))
        elif a is None:
            out.append(ArtifactDiff(path=path, change="removed",
                                    unified=_unified(b.content, "", path)))
        elif a.content != b.content:
            out.append(ArtifactDiff(path=path, change="modified",
                                    unified=_unified(b.content, a.content, path)))
        else:
            out.append(ArtifactDiff(path=path, change="unchanged"))
    return out


def _unified(before: str, after: str, path: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    ))
