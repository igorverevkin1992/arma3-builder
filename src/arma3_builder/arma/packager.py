"""Write the generated artefacts to disk in the canonical campaign layout."""
from __future__ import annotations

import zipfile
from pathlib import Path

from ..protocols import GeneratedArtifact


def package_campaign(
    artifacts: list[GeneratedArtifact],
    *,
    root: Path,
    name: str,
    create_zip: bool = False,
) -> Path:
    """Write artefacts under root/<name>/ and optionally produce a .zip archive."""
    target = Path(root) / name
    target.mkdir(parents=True, exist_ok=True)
    for art in artifacts:
        path = target / art.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(art.content, encoding="utf-8")

    if create_zip:
        zip_path = target.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for art in artifacts:
                zf.writestr(f"{name}/{art.relative_path}", art.content)
        return zip_path
    return target


def pbo_prefix_file(prefix: str) -> str:
    """Returns the contents of a $PBOPREFIX$ file."""
    return prefix.strip().rstrip("\n") + "\n"
