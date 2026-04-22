from arma3_builder.arma.stringtable import collect_strings, render_stringtable


def test_stringtable_includes_all_text(campaign_plan):
    strings = collect_strings(campaign_plan)
    # At least title + summary per mission.
    assert len(strings) >= 2 * len(campaign_plan.blueprints)
    xml = render_stringtable(campaign_plan, languages=["English", "Russian"])
    assert "<Project" in xml
    assert "<English>" in xml
    assert "<Russian>" in xml


def test_stringtable_escapes_specials(campaign_plan):
    campaign_plan.blueprints[0].brief.title = 'A & "B"'
    xml = render_stringtable(campaign_plan)
    assert "&amp;" in xml
    assert "&quot;" in xml
