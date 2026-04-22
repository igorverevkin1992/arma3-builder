"""In-process classname registry.

Used by the SQM/description generators when no RAG retriever is configured
(tests, offline runs). The registry maps `classname -> {addon, type, side}`.

Unknown classnames are NOT silently guessed. The caller gets an empty string
and `resolve_or_flag` collects unknowns so the QA pipeline can emit ERROR
findings — matching the TZ requirement to hard-block missing `addons[]`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import data_dir


@dataclass
class ClassnameInfo:
    classname: str
    addon: str
    type: str = "Object"
    faction: str = ""
    side: str = ""
    display_name: str = ""


@dataclass
class ClassnameRegistry:
    items: dict[str, ClassnameInfo] = field(default_factory=dict)
    unknown: set[str] = field(default_factory=set)

    def register(self, info: ClassnameInfo) -> None:
        self.items[info.classname] = info

    def addon_for(self, classname: str) -> str:
        info = self.items.get(classname)
        if info:
            return info.addon
        self.unknown.add(classname)
        return ""

    def is_known(self, classname: str) -> bool:
        return classname in self.items

    def filter(
        self,
        *,
        type: str | None = None,
        faction: str | None = None,
        side: str | None = None,
    ) -> list[ClassnameInfo]:
        out: list[ClassnameInfo] = []
        for info in self.items.values():
            if type and info.type != type:
                continue
            if faction and info.faction != faction:
                continue
            if side and info.side != side:
                continue
            out.append(info)
        return out

    @classmethod
    def from_seed_files(cls, directory: Path | None = None) -> ClassnameRegistry:
        directory = directory or (data_dir() / "seed_classnames")
        reg = cls()
        if not directory.exists():
            return reg
        for path in sorted(directory.glob("*.json")):
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            for entry in data.get("classnames", []):
                reg.register(ClassnameInfo(**entry))
        return reg

    def take_unknowns(self) -> list[str]:
        """Return and clear the list of classnames that could not be resolved."""
        out = sorted(self.unknown)
        self.unknown.clear()
        return out
