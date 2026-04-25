import pytest

from arma3_builder.llm import get_llm_client
from arma3_builder.pipeline.refine import refine_plan


@pytest.mark.asyncio
async def test_refine_stub_night(campaign_plan):
    llm = get_llm_client()
    new_plan = await refine_plan(
        campaign_plan, "make it a rainy night", llm=llm, model="stub",
    )
    for bp in new_plan.blueprints:
        assert bp.brief.time_of_day.startswith("23")
        assert bp.brief.weather == "rain"


@pytest.mark.asyncio
async def test_refine_stub_more_enemies(campaign_plan):
    llm = get_llm_client()
    before = len(campaign_plan.blueprints[0].units)
    new_plan = await refine_plan(
        campaign_plan, "add more enemies", llm=llm, model="stub",
    )
    after = len(new_plan.blueprints[0].units)
    assert after > before
