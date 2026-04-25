"""Ingest class definitions from PBO archives.

PBO is Bohemia's proprietary archive format. We don't implement it ourselves —
instead we shell out to one of the known unpacker CLIs and then run the normal
`ingest_config_cpp` over the extracted `config.cpp`. Supported tools (first
found wins):

  * ``armake2 unpack <pbo> <dir>``   — cross-platform Rust tool
  * ``extractpbo -P -F=config.cpp`` — Mikero's (Windows-centric)
  * ``derapify`` / ``armake``        — legacy fallbacks
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .ingest_classnames import ingest_config_cpp
from .store import VectorStore

_CANDIDATE_UNPACKERS: list[tuple[str, list[str]]] = [
    ("armake2", ["unpack", "{pbo}", "{dst}"]),
    ("extractpbo", ["-P", "-F=config.cpp", "{pbo}", "{dst}"]),
    ("armake", ["unpack", "{pbo}", "{dst}"]),
]


class UnpackerNotFound(RuntimeError):
    """No supported PBO unpacker is on PATH."""


def _find_unpacker() -> tuple[str, list[str]] | None:
    for name, template in _CANDIDATE_UNPACKERS:
        if shutil.which(name):
            return name, template
    return None


def unpack_pbo(pbo: Path, destination: Path) -> Path:
    """Extract `pbo` into `destination` and return the dir.

    Raises UnpackerNotFound if no tool is available.
    """
    chosen = _find_unpacker()
    if chosen is None:
        raise UnpackerNotFound(
            "No PBO unpacker found. Install `armake2` (cargo install armake2) "
            "or place Mikero's `extractpbo` on PATH."
        )
    name, template = chosen
    args = [name] + [seg.format(pbo=str(pbo), dst=str(destination)) for seg in template]
    subprocess.run(args, check=True, capture_output=True, timeout=120)
    return destination


def ingest_pbo(store: VectorStore, pbo: Path, *, tenant: str) -> int:
    """Unpack PBO → ingest its config.cpp. Returns count indexed."""
    with tempfile.TemporaryDirectory(prefix="arma3b_pbo_") as tmp:
        dst = Path(tmp)
        unpack_pbo(pbo, dst)
        # Locate config.cpp anywhere in the tree.
        configs = list(dst.rglob("config.cpp"))
        if not configs:
            return 0
        total = 0
        for cfg in configs:
            total += ingest_config_cpp(store, cfg, tenant=tenant)
        return total
