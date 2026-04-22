from arma3_builder.arma.campaign import (
    generate_campaign_description,
    mission_dir_name,
    slugify,
)


def test_slugify_basic():
    assert slugify("Operation Silent Reaper") == "Operation_Silent_Reaper"
    assert slugify("  ") == "campaign"


def test_mission_dir_name(mission_blueprint):
    assert mission_dir_name(mission_blueprint, 1) == "m01_Test_Mission.VR"


def test_campaign_description_links_first_mission(campaign_plan):
    text = generate_campaign_description(campaign_plan)
    # The blueprint's mission title drives the slug.
    assert 'firstBattle = "m01_Test_Mission"' in text
    assert "class Campaign" in text
    assert "class Chapter1" in text
    # Single mission -> end1 must point to the campaign-level "end" sink.
    assert 'end1 = "end"' in text
