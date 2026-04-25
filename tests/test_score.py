from arma3_builder.protocols import QAReport
from arma3_builder.qa.score import score_campaign


def test_score_all_axes_in_range(campaign_plan):
    qa = QAReport(findings=[], iteration=1)
    s = score_campaign(campaign_plan, qa)
    for axis in ("performance", "variety", "pacing", "balance", "narrative", "overall"):
        v = getattr(s, axis)
        assert 0 <= v <= 100


def test_performance_collapses_on_error(campaign_plan):
    from arma3_builder.protocols import QAFinding, Severity
    qa = QAReport(findings=[
        QAFinding(file="x.sqf", severity=Severity.ERROR, code="A3B001",
                  message="bad"),
    ], iteration=1)
    s = score_campaign(campaign_plan, qa)
    assert s.performance < 50
