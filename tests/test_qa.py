from arma3_builder.protocols import GeneratedArtifact, Severity
from arma3_builder.qa.analyzer import analyze_artifacts, build_qa_report


def _sqf(name, content):
    return GeneratedArtifact(relative_path=name, content=content, kind="sqf")


def test_detects_bis_fnc_mp():
    art = _sqf("missions/m01/initServer.sqf", "[player] call BIS_fnc_MP;\n")
    findings = analyze_artifacts([art], use_sqflint=False)
    codes = {f.code for f in findings}
    assert "A3B001" in codes
    assert any(f.severity == Severity.ERROR for f in findings if f.code == "A3B001")


def test_detects_busy_loop_without_sleep():
    art = _sqf("missions/m01/init.sqf", "[] spawn { while {true} do { hint \"x\" } };\n")
    findings = analyze_artifacts([art], use_sqflint=False)
    assert any(f.code == "A3B002" for f in findings)


def test_busy_loop_with_sleep_is_clean():
    art = _sqf("missions/m01/init.sqf",
               "[] spawn { while {true} do { sleep 1; hint \"x\" } };\n")
    findings = analyze_artifacts([art], use_sqflint=False)
    assert not any(f.code == "A3B002" for f in findings)


def test_detects_global_setmarkerpos():
    art = _sqf("missions/m01/init.sqf",
               '"alpha" setMarkerPos getPos player;\n')
    findings = analyze_artifacts([art], use_sqflint=False)
    assert any(f.code == "A3B004" for f in findings)


def test_endstate_validation(campaign_plan):
    from arma3_builder.agents.config_master import ConfigMasterAgent
    from arma3_builder.arma.classnames import ClassnameRegistry

    import asyncio

    cm = ConfigMasterAgent()
    ctx_like = type("Ctx", (), {"registry": ClassnameRegistry.from_seed_files()})()

    async def run():
        from arma3_builder.agents.base import AgentContext
        from arma3_builder.llm import get_llm_client
        from arma3_builder.rag import HybridRetriever

        ctx = AgentContext(
            llm=get_llm_client(),
            retriever=HybridRetriever(),
            registry=ctx_like.registry,
        )
        files, _ = await cm.run(campaign_plan, ctx)
        return files

    files = asyncio.get_event_loop().run_until_complete(run()) if False else asyncio.run(run())
    report = build_qa_report(campaign_plan, files, iteration=1, use_sqflint=False)
    # All declared end states should be matched -> no A3B200 errors.
    assert not [f for f in report.findings if f.code == "A3B200"]
