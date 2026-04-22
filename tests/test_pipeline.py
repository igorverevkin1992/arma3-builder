import asyncio
from pathlib import Path

import pytest

from arma3_builder.pipeline import Pipeline, PipelineConfig


@pytest.fixture()
def pipeline(tmp_path) -> Pipeline:
    cfg = PipelineConfig(output_dir=tmp_path, qa_strict=False, max_iterations=3)
    return Pipeline(config=cfg)


@pytest.mark.asyncio
async def test_pipeline_from_brief_writes_files(pipeline, campaign_brief, tmp_path):
    result = await pipeline.generate_from_brief(campaign_brief)

    assert result.output_path is not None
    out = Path(result.output_path)
    assert out.exists()
    assert (out / "Description.ext").exists()
    assert (out / "config.cpp").exists()

    mission_dirs = list((out / "missions").iterdir())
    assert mission_dirs
    mdir = mission_dirs[0]
    for f in ["description.ext", "mission.sqm", "init.sqf",
              "initServer.sqf", "initPlayerLocal.sqf", "briefing.sqf",
              "functions/fn_initFsm.sqf"]:
        assert (mdir / f).exists(), f"missing {f}"


@pytest.mark.asyncio
async def test_pipeline_from_prompt_uses_stub(pipeline):
    result = await pipeline.generate("Coop campaign for spec ops on Tanoa, two missions")
    assert result.plan.brief.name
    assert len(result.artifacts) > 0
    # No A3B200 errors expected for the stub plan.
    end_state_errors = [f for f in result.qa.findings if f.code == "A3B200"]
    assert end_state_errors == []


@pytest.mark.asyncio
async def test_repair_fixes_bis_fnc_mp(pipeline):
    """Inject a bad SQF artifact and confirm the repair() loop rewrites it."""
    result = await pipeline.generate_from_brief(
        # any brief works — we'll mutate the artifacts after generation
        __import__("arma3_builder.protocols", fromlist=["CampaignBrief"]).CampaignBrief(
            name="Repair Test",
            overview="t",
            mods=["cba_main"],
            factions={"WEST": "BLU_F"},
            missions=[__import__("arma3_builder.protocols", fromlist=["MissionBrief"]).MissionBrief(
                title="m", summary="s", map="VR",
            )],
        )
    )
    sqf = next(a for a in result.artifacts if a.relative_path.endswith("init.sqf"))
    sqf.content += "\n[player] call BIS_fnc_MP;\n"
    ctx = pipeline.make_context()
    report = await pipeline.qa.run(result.plan, result.artifacts, ctx, iteration=1)
    assert any(f.code == "A3B001" for f in report.findings)
    fixed = await pipeline.scripter.repair(result.artifacts, report, ctx)
    assert "BIS_fnc_MP" not in next(a.content for a in fixed if a.relative_path.endswith("init.sqf"))
