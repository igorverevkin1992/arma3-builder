"""In-process classname registry.

Used by the SQM/description generators when no RAG retriever is configured
(tests, offline runs). The registry maps `classname -> {addon, type, side}`.
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


@dataclass
class ClassnameRegistry:
    items: dict[str, ClassnameInfo] = field(default_factory=dict)

    def register(self, info: ClassnameInfo) -> None:
        self.items[info.classname] = info

    def addon_for(self, classname: str) -> str:
        info = self.items.get(classname)
        if info:
            return info.addon
        # heuristic fallback for unknown classnames: prefix-based guess
        for prefix, addon in _PREFIX_GUESS.items():
            if classname.startswith(prefix):
                return addon
        return ""

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


_PREFIX_GUESS = {
    "rhsusf_": "rhsusf_main",
    "rhs_": "rhs_main_loadorder",
    "CUP_": "cup_units_core",
    "ace_": "ace_main",
    "B_": "A3_Characters_F",
    "O_": "A3_Characters_F",
    "I_": "A3_Characters_F",
    "C_": "A3_Characters_F_Beta",
}
