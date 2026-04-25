"""Catalogue of antipattern rules used by the QA analyser.

Each rule is a regex with metadata; the analyser scans every SQF artefact and
emits a structured QAFinding when a rule matches. Rules are deliberately
narrow — false positives slow the repair loop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..protocols import Severity


@dataclass
class Rule:
    code: str
    pattern: re.Pattern[str]
    severity: Severity
    message: str
    suggestion: str


RULES: list[Rule] = [
    Rule(
        code="A3B001",
        pattern=re.compile(r"\bBIS_fnc_MP\b"),
        severity=Severity.ERROR,
        message="BIS_fnc_MP is deprecated and unsafe",
        suggestion="Replace with `remoteExec` / `remoteExecCall` and an explicit target",
    ),
    Rule(
        code="A3B002",
        pattern=re.compile(r"while\s*\{\s*true\s*\}\s*do\s*\{(?![^{}]*\bsleep\b)(?![^{}]*\buiSleep\b)[^{}]*\}"),
        severity=Severity.ERROR,
        message="Infinite loop without sleep — instant FPS collapse",
        suggestion="Add `sleep`/`uiSleep` or replace with `CBA_fnc_addPerFrameHandler`",
    ),
    Rule(
        # Only flag execVM when it sits inside a repetition / event context.
        # A one-shot execVM (e.g. firing briefing.sqf from initPlayerLocal)
        # is fine; flagging it spammed the QA report without value.
        code="A3B003",
        pattern=re.compile(
            r"(?:forEach|while\s*\{|for\s*\[|addAction|addEventHandler|"
            r"addMissionEventHandler|spawn|onEachFrame)[^;]*?\bexecVM\b\s*\"[^\"]+\.sqf\"",
            re.DOTALL,
        ),
        severity=Severity.WARNING,
        message="execVM inside loop/event context — pre-compile via CfgFunctions",
        suggestion="Move the script to CfgFunctions and `call A3B_fnc_xxx` instead",
    ),
    Rule(
        code="A3B004",
        pattern=re.compile(r"\bsetMarkerPos\b(?!\w*Local)"),
        severity=Severity.WARNING,
        message="Global setMarkerPos in MP code can saturate the network channel",
        suggestion="Use `setMarkerPosLocal` and broadcast on important state changes only",
    ),
    Rule(
        code="A3B005",
        pattern=re.compile(r"^\s*[A-Za-z_][\w]*\s*=\s*[^;{}\n]+(?<![{};])\s*$", re.MULTILINE),
        severity=Severity.ERROR,
        message="Statement does not end with `;`",
        suggestion="Append `;` to the assignment / call",
    ),
    Rule(
        code="A3B006",
        pattern=re.compile(r"\bglobalSetPos\b|setPos\s*\[[^\]]+\]\s*;?\s*$"),
        severity=Severity.INFO,
        message="Global setPos used for movement — may overload net",
        suggestion="Prefer `attachTo` for object following or local simulation",
    ),
    Rule(
        code="A3B007",
        pattern=re.compile(r"\bspawn\b\s*\{[^}]*\bwhile\s*\{\s*true\s*\}\s*do\b[^}]*\}"),
        severity=Severity.WARNING,
        message="Spawned worker with infinite loop — use a per-frame handler instead",
        suggestion="`[code, 0.1] call CBA_fnc_addPerFrameHandler`",
    ),
]
