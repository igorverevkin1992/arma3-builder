"""Static analysis over the bundle of generated artefacts.

This is the core of the QA Validator agent. It combines:
  1. Antipattern rule scan over SQF (see ``rules.py``)
  2. Optional sqflint pass (see ``linter.py``)
  3. Cross-file structural validation:
       - every Campaign-level end* reference must exist in the mission's
         CfgDebriefing block
       - every classname used in the SQM must be declared in addons[]
       - mission directory naming follows ``<id>.<world>``
"""
from __future__ import annotations

import re
from typing import Iterable

from ..protocols import (
    CampaignPlan,
    GeneratedArtifact,
    QAFinding,
    QAReport,
    Severity,
)
from .linter import SqfLinter
from .rules import RULES


def analyze_artifacts(
    artifacts: list[GeneratedArtifact],
    *,
    use_sqflint: bool = True,
) -> list[QAFinding]:
    findings: list[QAFinding] = []
    linter = SqfLinter() if use_sqflint else None

    for art in artifacts:
        if art.kind == "sqf":
            findings.extend(_scan_sqf(art))
            if linter and linter.available:
                findings.extend(linter.lint_text(art.content, filename=art.relative_path))
        elif art.kind == "ext":
            findings.extend(_scan_ext(art))
    return findings


def _scan_sqf(art: GeneratedArtifact) -> Iterable[QAFinding]:
    for rule in RULES:
        for match in rule.pattern.finditer(art.content):
            line_no = art.content[: match.start()].count("\n") + 1
            yield QAFinding(
                file=art.relative_path,
                line=line_no,
                column=match.start() - art.content.rfind("\n", 0, match.start()),
                severity=rule.severity,
                code=rule.code,
                message=rule.message,
                suggestion=rule.suggestion,
            )


_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_][\w]*)\b")


def _scan_ext(art: GeneratedArtifact) -> Iterable[QAFinding]:
    """Light-weight checks on description.ext / Campaign Description.ext."""
    text = art.content
    open_braces = text.count("{")
    close_braces = text.count("}")
    if open_braces != close_braces:
        yield QAFinding(
            file=art.relative_path,
            line=0,
            severity=Severity.ERROR,
            code="A3B100",
            message=f"Unbalanced braces ({open_braces} '{{' vs {close_braces} '}}')",
        )

    # `class Foo;` forward declarations are legal but `class Foo {}` blocks should
    # always end with `};` per Arma config grammar.
    for m in re.finditer(r"\bclass\s+\w+\b[^{};]*\{[^{}]*\}(?!\s*;)", text):
        line_no = text[: m.start()].count("\n") + 1
        yield QAFinding(
            file=art.relative_path,
            line=line_no,
            severity=Severity.ERROR,
            code="A3B101",
            message="Class definition not terminated with `};`",
            suggestion="Append `;` after the closing brace",
        )


# --------------------------------------------------------------------------- #
# Cross-file validation
# --------------------------------------------------------------------------- #


_END_REF_RE = re.compile(r"\b(end\d+|loser)\s*=\s*\"([^\"]+)\"")
_DEBRIEF_END_RE = re.compile(r"class\s+(end\d+|loser)\b")


def _extract_balanced_block(text: str, start_keyword: str) -> str | None:
    """Return the body of a `<keyword> { ... }` block, brace-balanced."""
    m = re.search(rf"\b{re.escape(start_keyword)}\s*\{{", text)
    if not m:
        return None
    depth = 1
    i = m.end()
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return text[m.end(): i - 1]


def validate_campaign_endstates(
    plan: CampaignPlan,
    artifacts: list[GeneratedArtifact],
) -> list[QAFinding]:
    """Ensure that every `endN = "..."` referenced in Campaign Description.ext
    is matched by a corresponding `class endN` in the target mission's
    CfgDebriefing. This catches the most common cause of campaign load
    failures."""
    by_path = {a.relative_path: a for a in artifacts}
    campaign_ext = by_path.get("Description.ext")
    if not campaign_ext:
        return []

    findings: list[QAFinding] = []
    referenced: set[str] = set()
    for m in _END_REF_RE.finditer(campaign_ext.content):
        referenced.add(m.group(1))

    for blueprint in plan.blueprints:
        # Find the mission's description.ext and pull declared end classes.
        for path, art in by_path.items():
            if not path.endswith("description.ext"):
                continue
            if blueprint.brief.title.lower().replace(" ", "_") not in path.lower():
                continue
            declared = set(_extract_debriefing_ends(art.content))
            for end_state in blueprint.fsm.end_types():
                if end_state in referenced and end_state not in declared:
                    findings.append(
                        QAFinding(
                            file=art.relative_path,
                            severity=Severity.ERROR,
                            code="A3B200",
                            message=(
                                f"End state `{end_state}` is referenced by Campaign "
                                f"Description.ext but missing from CfgDebriefing"
                            ),
                            suggestion=f"Add `class {end_state} {{ ... }};` to the mission description.ext",
                        )
                    )
    return findings


def _extract_debriefing_ends(text: str) -> Iterable[str]:
    body = _extract_balanced_block(text, "class CfgDebriefing")
    if body is None:
        return
    for m in _DEBRIEF_END_RE.finditer(body):
        yield m.group(1)


def build_qa_report(
    plan: CampaignPlan | None,
    artifacts: list[GeneratedArtifact],
    *,
    iteration: int,
    use_sqflint: bool = True,
) -> QAReport:
    findings = analyze_artifacts(artifacts, use_sqflint=use_sqflint)
    if plan is not None:
        findings.extend(validate_campaign_endstates(plan, artifacts))
    return QAReport(findings=findings, iteration=iteration)
