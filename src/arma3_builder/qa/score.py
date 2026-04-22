"""Campaign quality score — 5-axis radar metric.

Produces a 0..100 score on each axis plus an overall weighted score. Used by
the web UI to give designers a quick "how good is this?" readout beyond the
binary QA pass/fail.

Axes:
  * Performance   — zero ERROR, low WARNING count in performance rules
  * Variety       — number of unique unit classnames + faction diversity
  * Pacing        — balanced distribution of FSM nodes (not too empty, not too bursty)
  * Balance       — ratio of player-side to enemy-side combatants within [0.3..0.7]
  * Narrative     — presence of diary entries, tasks, dialogue lines
"""
from __future__ import annotations

from dataclasses import dataclass

from ..protocols import CampaignPlan, QAReport


@dataclass
class QualityScore:
    performance: int
    variety: int
    pacing: int
    balance: int
    narrative: int
    overall: int

    def to_dict(self) -> dict[str, int]:
        return {
            "performance": self.performance,
            "variety": self.variety,
            "pacing": self.pacing,
            "balance": self.balance,
            "narrative": self.narrative,
            "overall": self.overall,
        }


_PERF_RULES = {"A3B001", "A3B002", "A3B003", "A3B007"}


def score_campaign(plan: CampaignPlan, qa: QAReport) -> QualityScore:
    perf = _score_performance(qa)
    variety = _score_variety(plan)
    pacing = _score_pacing(plan)
    balance = _score_balance(plan)
    narrative = _score_narrative(plan)
    overall = round(
        perf * 0.30 + variety * 0.15 + pacing * 0.20 + balance * 0.15 + narrative * 0.20
    )
    return QualityScore(
        performance=perf, variety=variety, pacing=pacing,
        balance=balance, narrative=narrative, overall=int(overall),
    )


def _score_performance(qa: QAReport) -> int:
    # Any ERROR in a perf rule collapses the score.
    perf_errors = sum(1 for f in qa.errors if f.code in _PERF_RULES)
    perf_warns = sum(1 for f in qa.warnings if f.code in _PERF_RULES)
    if perf_errors:
        return max(0, 40 - 10 * perf_errors)
    return max(0, 100 - 8 * perf_warns)


def _score_variety(plan: CampaignPlan) -> int:
    classes: set[str] = set()
    sides: set[str] = set()
    for bp in plan.blueprints:
        for u in bp.units:
            classes.add(u.classname)
            sides.add(u.side)
    base = min(100, 40 + 10 * len(classes))
    # Bonus for 2+ sides per mission.
    if len(sides) >= 2:
        base = min(100, base + 10)
    return base


def _score_pacing(plan: CampaignPlan) -> int:
    if not plan.blueprints:
        return 0
    scores: list[int] = []
    for bp in plan.blueprints:
        n = len(bp.fsm.states)
        # 3 is skeletal, 5–7 is ideal, 10+ is over-engineered.
        if n < 3:
            scores.append(30)
        elif n > 10:
            scores.append(60)
        else:
            scores.append(60 + (min(n, 7) - 3) * 10)
    return round(sum(scores) / len(scores))


def _score_balance(plan: CampaignPlan) -> int:
    # Ratio players:enemies close to 1:2 is ideal (challenging but winnable).
    total = 0
    for bp in plan.blueprints:
        players = sum(1 for u in bp.units if u.is_player)
        enemies = sum(1 for u in bp.units if u.side == bp.brief.enemy_side)
        if players == 0 or enemies == 0:
            total += 40
            continue
        ratio = players / (players + enemies)
        # Peak at 0.33 (1:2); fall off at 0 and 1.
        score = int(max(0, 100 - abs(ratio - 0.33) * 200))
        total += score
    return round(total / max(1, len(plan.blueprints)))


def _score_narrative(plan: CampaignPlan) -> int:
    if not plan.blueprints:
        return 0
    total = 0
    for bp in plan.blueprints:
        diary = len(bp.diary.entries)
        tasks = len(bp.diary.tasks)
        dialog = len(bp.dialogue)
        per_mission = 10 + diary * 10 + tasks * 10 + dialog * 15
        total += min(100, per_mission)
    return round(total / len(plan.blueprints))
