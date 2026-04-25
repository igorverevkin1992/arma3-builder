"""Mission pacing analyser.

Classifies every FSM state into a `StateKind`, estimates its duration, and
emits findings about rhythm problems (long dead-zones, burst overlaps,
unreachable paths from a pacing perspective). The output feeds:

  * the 5-axis quality score (improves the `pacing` axis)
  * the web UI timeline chart
  * QA report when a rhythm problem crosses the threshold
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..protocols import (
    CampaignPlan,
    FsmGraph,
    FsmState,
    QAFinding,
    Severity,
    StateKind,
)

# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #

# Keyword buckets for the heuristic classifier. The first bucket whose any
# keyword is present in the state's label / on_enter code wins.
_BUCKETS: list[tuple[StateKind, list[str]]] = [
    (StateKind.CUTSCENE,   ["cutscene", "titleText", "BIS_fnc_establishingShot", "camera"]),
    (StateKind.DIALOGUE,   ["kbTell", "dialogue", "brief", "sideChat", "radio"]),
    (StateKind.STEALTH,    ["stealth", "infiltrat", "sneak", "observe", "recon"]),
    (StateKind.ENGAGEMENT, ["ambush", "engage", "attack", "defend", "fight",
                            "combat", "assault", "clear", "hold"]),
    (StateKind.EXTRACTION, ["extract", "exfil", "evac", "win", "end1"]),
    (StateKind.TRAVEL,     ["depart", "move", "approach", "transit", "drive", "fly",
                            "insert", "locate"]),
    (StateKind.SETUP,      ["prepare", "setup", "init", "brief"]),
]

# Heuristic duration (seconds) per kind — used when `expected_seconds` is
# not set on the state. Grounded in ballpark playthroughs of community
# missions (DUWS, Escape, CO40 etc.).
DEFAULT_DURATION: dict[StateKind, int] = {
    StateKind.SETUP:      60,
    StateKind.TRAVEL:     240,
    StateKind.ENGAGEMENT: 180,
    StateKind.STEALTH:    300,
    StateKind.DIALOGUE:   30,
    StateKind.CUTSCENE:   45,
    StateKind.EXTRACTION: 120,
    StateKind.GENERIC:    90,
    StateKind.TERMINAL:   0,
}


def classify_state(state: FsmState) -> StateKind:
    """Return the state's declared kind, or infer from its content."""
    if state.is_terminal:
        return StateKind.TERMINAL
    if state.kind != StateKind.GENERIC:
        return state.kind
    blob = " ".join([state.id, state.label] + state.on_enter).lower()
    for kind, keywords in _BUCKETS:
        for kw in keywords:
            if kw.lower() in blob:
                return kind
    return StateKind.GENERIC


def estimate_duration(state: FsmState) -> int:
    """Return the expected dwell time (seconds) for the state."""
    if state.expected_seconds is not None:
        return state.expected_seconds
    kind = classify_state(state)
    # If a transition is TIMER with a numeric condition, it beats the default.
    for tr in state.transitions:
        if tr.kind.value == "timer":
            try:
                return int(float(tr.condition))
            except (TypeError, ValueError):
                pass
    return DEFAULT_DURATION.get(kind, 90)


# --------------------------------------------------------------------------- #
# Timeline & findings
# --------------------------------------------------------------------------- #


@dataclass
class TimelineSegment:
    state_id: str
    label: str
    kind: str
    seconds: int

    def to_dict(self) -> dict:
        return {
            "state_id": self.state_id,
            "label": self.label,
            "kind": self.kind,
            "seconds": self.seconds,
        }


@dataclass
class MissionPacing:
    mission_id: str
    timeline: list[TimelineSegment] = field(default_factory=list)
    findings: list[QAFinding] = field(default_factory=list)

    @property
    def total_seconds(self) -> int:
        return sum(s.seconds for s in self.timeline)

    @property
    def engagement_seconds(self) -> int:
        return sum(s.seconds for s in self.timeline
                   if s.kind == StateKind.ENGAGEMENT.value)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "timeline": [s.to_dict() for s in self.timeline],
            "total_seconds": self.total_seconds,
            "engagement_ratio": (
                round(self.engagement_seconds / self.total_seconds, 3)
                if self.total_seconds else 0.0
            ),
            "findings": [f.model_dump() for f in self.findings],
        }


@dataclass
class CampaignPacing:
    missions: list[MissionPacing] = field(default_factory=list)

    @property
    def findings(self) -> list[QAFinding]:
        return [f for m in self.missions for f in m.findings]

    def to_dict(self) -> dict:
        return {
            "missions": [m.to_dict() for m in self.missions],
            "total_seconds": sum(m.total_seconds for m in self.missions),
        }


def _greedy_happy_path(fsm: FsmGraph) -> list[FsmState]:
    """Pick the first-listed transition from each state until we hit a
    terminal state. Good enough for an estimate — the Playtester agent
    (A4) explores full reachability separately."""
    by_id = {s.id: s for s in fsm.states}
    if fsm.initial not in by_id:
        return []
    seen: set[str] = set()
    current = by_id[fsm.initial]
    path: list[FsmState] = []
    while current.id not in seen:
        seen.add(current.id)
        path.append(current)
        if current.is_terminal or not current.transitions:
            break
        next_id = current.transitions[0].to
        if next_id not in by_id:
            break
        current = by_id[next_id]
    return path


def analyse_mission(mission_id: str, fsm: FsmGraph) -> MissionPacing:
    timeline: list[TimelineSegment] = []
    for state in _greedy_happy_path(fsm):
        kind = classify_state(state)
        timeline.append(TimelineSegment(
            state_id=state.id,
            label=state.label,
            kind=kind.value,
            seconds=estimate_duration(state),
        ))
    report = MissionPacing(mission_id=mission_id, timeline=timeline)

    # Finding: mission is mostly travel / has no engagement at all.
    eng = report.engagement_seconds
    total = report.total_seconds
    if total >= 120 and eng == 0:
        report.findings.append(QAFinding(
            file=f"missions/{mission_id}",
            severity=Severity.WARNING,
            code="A3B310",
            message=(
                f"No engagement states in {mission_id} — {total}s of pure "
                "travel/dialogue will feel hollow."
            ),
            suggestion="Add at least one StateKind.ENGAGEMENT state, or label "
                       "an existing combat state with kind=engagement.",
        ))

    # Finding: long dead-zone — 600+s without an engagement/dialogue beat.
    run_without_beat = 0
    for seg in timeline:
        if seg.kind in {StateKind.ENGAGEMENT.value,
                        StateKind.DIALOGUE.value,
                        StateKind.CUTSCENE.value}:
            run_without_beat = 0
        else:
            run_without_beat += seg.seconds
            if run_without_beat >= 600:
                report.findings.append(QAFinding(
                    file=f"missions/{mission_id}",
                    severity=Severity.WARNING,
                    code="A3B311",
                    message=(
                        f"Dead-zone of {run_without_beat}s ending at "
                        f"`{seg.state_id}` — break it up with a radio beat or "
                        "scripted event."
                    ),
                    suggestion="Insert a StateKind.DIALOGUE or CUTSCENE beat.",
                ))
                run_without_beat = 0  # reset so we don't double-fire

    # Finding: burst — 3+ consecutive engagement states with no rest.
    run_engagement = 0
    for seg in timeline:
        if seg.kind == StateKind.ENGAGEMENT.value:
            run_engagement += 1
            if run_engagement >= 3:
                report.findings.append(QAFinding(
                    file=f"missions/{mission_id}",
                    severity=Severity.INFO,
                    code="A3B312",
                    message=(
                        f"{run_engagement} consecutive engagement states — "
                        "players will fatigue; insert travel or cutscene."
                    ),
                    suggestion="Add a StateKind.TRAVEL or CUTSCENE between "
                               "engagements.",
                ))
                break
        else:
            run_engagement = 0

    # Finding: mission too long (>60 minutes is unusual for Arma coop).
    if total > 60 * 60:
        report.findings.append(QAFinding(
            file=f"missions/{mission_id}",
            severity=Severity.INFO,
            code="A3B313",
            message=f"Estimated playthrough of {total // 60} min — "
                    "consider splitting into two missions.",
        ))
    return report


def analyse_campaign(plan: CampaignPlan) -> CampaignPacing:
    out = CampaignPacing()
    for bp in plan.blueprints:
        mid = bp.mission_id or bp.brief.title
        out.missions.append(analyse_mission(mid, bp.fsm))
    return out


# Shortcut for the QA report aggregator.
def pacing_findings(plan: CampaignPlan) -> list[QAFinding]:
    return analyse_campaign(plan).findings
