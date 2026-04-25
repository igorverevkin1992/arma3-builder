"""Simulated playthrough — does the FSM actually finish?

The Playtester walks each mission's FSM and checks three safety properties:

  1. **Reachability**: every state is reachable from `initial`.
  2. **Liveness**: at least one terminal state is reachable (no dead ends
     from which progression is impossible).
  3. **Determinability**: transition conditions are either timer-based, use
     known namespace variables set in `on_enter_global`, or reference
     entities the SQM actually contains.

Findings are emitted as QA artefacts at severity ERROR for unreachable
states and WARNING for questionable conditions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..protocols import (
    CampaignPlan,
    FsmGraph,
    MissionBlueprint,
    QAFinding,
    Severity,
    TransitionKind,
)

# --------------------------------------------------------------------------- #
# Reachability / liveness
# --------------------------------------------------------------------------- #


def _reachable_states(fsm: FsmGraph) -> set[str]:
    by_id = {s.id: s for s in fsm.states}
    if fsm.initial not in by_id:
        return set()
    stack = [fsm.initial]
    seen: set[str] = set()
    while stack:
        sid = stack.pop()
        if sid in seen:
            continue
        seen.add(sid)
        state = by_id.get(sid)
        if not state:
            continue
        for tr in state.transitions:
            if tr.to in by_id:
                stack.append(tr.to)
    return seen


def _reaches_terminal(fsm: FsmGraph, start: str) -> bool:
    by_id = {s.id: s for s in fsm.states}
    stack = [start]
    seen: set[str] = set()
    while stack:
        sid = stack.pop()
        if sid in seen:
            continue
        seen.add(sid)
        state = by_id.get(sid)
        if not state:
            continue
        if state.is_terminal and state.end_type:
            return True
        for tr in state.transitions:
            stack.append(tr.to)
    return False


# --------------------------------------------------------------------------- #
# Condition sanity
# --------------------------------------------------------------------------- #


_A3B_VAR_RE = re.compile(r"\bA3B_([A-Za-z][\w]*)\b")
_UNIT_REF_RE = re.compile(r"\b([pe]\d+)\b")


def _collect_known_variables(blueprint: MissionBlueprint) -> tuple[set[str], set[str]]:
    """Return the set of A3B_* variable names and `pN/eN` unit names that the
    mission is guaranteed to have at runtime."""
    a3b_vars: set[str] = set()
    for stmt in blueprint.fsm.on_enter_global:
        for m in _A3B_VAR_RE.finditer(stmt):
            a3b_vars.add(m.group(1))
    for state in blueprint.fsm.states:
        for stmt in state.on_enter + state.on_exit:
            for m in _A3B_VAR_RE.finditer(stmt):
                a3b_vars.add(m.group(1))

    unit_names: set[str] = {u.name for u in blueprint.units if u.name}
    return a3b_vars, unit_names


def _check_condition(
    condition: str, known_vars: set[str], unit_names: set[str]
) -> str | None:
    """Return a human-readable issue with the condition, or None."""
    refs_a3b = {m.group(1) for m in _A3B_VAR_RE.finditer(condition)}
    unknown = refs_a3b - known_vars
    if unknown:
        return f"references undefined namespace variable(s): {sorted(unknown)}"

    refs_units = {m.group(1) for m in _UNIT_REF_RE.finditer(condition)}
    missing_units = refs_units - unit_names
    if missing_units:
        return f"references unit name(s) not placed in SQM: {sorted(missing_units)}"
    return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


@dataclass
class PlaytestReport:
    mission_id: str
    reachable: set[str] = field(default_factory=set)
    unreachable: set[str] = field(default_factory=set)
    dead_ends: set[str] = field(default_factory=set)
    findings: list[QAFinding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "reachable": sorted(self.reachable),
            "unreachable": sorted(self.unreachable),
            "dead_ends": sorted(self.dead_ends),
            "findings": [f.model_dump() for f in self.findings],
        }


def playtest_mission(blueprint: MissionBlueprint) -> PlaytestReport:
    mid = blueprint.mission_id or blueprint.brief.title
    report = PlaytestReport(mission_id=mid)

    fsm = blueprint.fsm
    by_id = {s.id: s for s in fsm.states}

    # 1. Reachability
    reachable = _reachable_states(fsm)
    report.reachable = reachable
    report.unreachable = {s.id for s in fsm.states if s.id not in reachable}
    for sid in sorted(report.unreachable):
        report.findings.append(QAFinding(
            file=f"missions/{mid}",
            severity=Severity.ERROR,
            code="A3B301",
            message=f"State `{sid}` is unreachable from initial `{fsm.initial}`",
            suggestion=(
                "Add a transition into this state, remove it, or fix the "
                "`initial` field."
            ),
        ))

    # 2. Liveness — every reachable state must be able to reach a terminal.
    for sid in sorted(reachable):
        state = by_id[sid]
        if state.is_terminal:
            continue
        if not _reaches_terminal(fsm, sid):
            report.dead_ends.add(sid)
            report.findings.append(QAFinding(
                file=f"missions/{mid}",
                severity=Severity.ERROR,
                code="A3B302",
                message=(
                    f"State `{sid}` cannot reach any terminal state — mission "
                    "will hang here forever."
                ),
                suggestion="Add a transition towards a terminal state or a "
                           "loser fallback.",
            ))

    # 3. Condition sanity.
    known_vars, unit_names = _collect_known_variables(blueprint)
    for state in fsm.states:
        for tr in state.transitions:
            if tr.kind == TransitionKind.TIMER:
                continue
            issue = _check_condition(tr.condition, known_vars, unit_names)
            if issue:
                report.findings.append(QAFinding(
                    file=f"missions/{mid}",
                    severity=Severity.WARNING,
                    code="A3B303",
                    message=f"Transition {state.id} → {tr.to}: {issue}",
                    suggestion=(
                        "Declare the variable in `fsm.on_enter_global`, name "
                        "the unit in the SQM, or remove the reference."
                    ),
                ))

    # 4. Initial state must exist.
    if fsm.initial not in by_id:
        report.findings.append(QAFinding(
            file=f"missions/{mid}",
            severity=Severity.ERROR,
            code="A3B304",
            message=f"FSM initial state `{fsm.initial}` does not exist",
        ))

    return report


def playtest_campaign(plan: CampaignPlan) -> list[PlaytestReport]:
    return [playtest_mission(bp) for bp in plan.blueprints]


def playtest_findings(plan: CampaignPlan) -> list[QAFinding]:
    """Flattened findings for the QA report aggregator."""
    return [f for r in playtest_campaign(plan) for f in r.findings]
