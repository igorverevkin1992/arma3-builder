"""Wrapper around the external `sqflint` CLI with a graceful no-op fallback."""
from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..protocols import QAFinding, Severity


class SqfLinter:
    """Calls the `sqflint` binary if present.

    Output format from sqflint is `path:line:col:level:message`. We translate
    this directly into QAFinding objects so they integrate with the QA report.
    """

    def __init__(self, binary: str = "sqflint") -> None:
        self.binary = binary
        self.available = shutil.which(binary) is not None

    def lint_text(self, content: str, *, filename: str = "snippet.sqf") -> list[QAFinding]:
        if not self.available:
            return []
        with tempfile.NamedTemporaryFile("w", suffix=".sqf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            return self._run([str(tmp_path)], display_name=filename)
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()

    def lint_file(self, path: Path) -> list[QAFinding]:
        if not self.available:
            return []
        return self._run([str(path)], display_name=str(path))

    # -------------------------------------------------------------- internal

    def _run(self, args: list[str], *, display_name: str) -> list[QAFinding]:
        # Don't pass -r (recursive) — every call here is a single file. The
        # earlier `-r` was a leftover from a CLI that walked directories and
        # confused some sqflint versions into ignoring the file argument.
        try:
            proc = subprocess.run(
                [self.binary, *args],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        return list(self._parse_output(proc.stdout + "\n" + proc.stderr, display_name))

    def _parse_output(self, output: str, display_name: str):
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(":", 4)
            if len(parts) < 5:
                continue
            _path, lineno, col, level, message = parts
            try:
                ln = int(lineno)
                cn = int(col)
            except ValueError:
                ln, cn = 0, 0
            yield QAFinding(
                file=display_name,
                line=ln,
                column=cn,
                severity=_severity(level),
                code="SQFLINT",
                message=message.strip(),
            )


def _severity(token: str) -> Severity:
    t = token.strip().lower()
    if t in {"error", "err"}:
        return Severity.ERROR
    if t in {"warning", "warn"}:
        return Severity.WARNING
    return Severity.INFO
