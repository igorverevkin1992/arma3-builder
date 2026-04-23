"""End-to-end pipeline: prompt → CampaignBrief → CampaignPlan → artefacts → QA.

The pipeline is fully async and supports a repair loop bounded by
`max_repair_iterations`. Each iteration:

  1. Scripter regenerates SQF for any mission whose files were flagged.
  2. QA re-runs the analyser/linter pass.
  3. Loop exits when QA is clean (or strict mode is satisfied) or the
     iteration cap is reached.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..agents import (
    AgentContext,
    ConfigMasterAgent,
    NarrativeAgent,
    OrchestratorAgent,
    QAAgent,
    ScripterAgent,
)
from ..arma.classnames import ClassnameRegistry
from ..arma.packager import package_campaign
from ..config import get_settings
from ..llm import LLMClient, get_llm_client, usage_accumulator
from ..protocols import (
    CampaignBrief,
    CampaignPlan,
    GeneratedArtifact,
    GenerationResult,
)
from ..qa.pacing import analyse_campaign
from ..qa.playtester import playtest_campaign
from ..rag import HybridRetriever, bootstrap
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PipelineConfig:
    output_dir: Path = field(default_factory=lambda: get_settings().output_dir)
    qa_strict: bool = field(default_factory=lambda: get_settings().qa_strict)
    max_iterations: int = field(default_factory=lambda: get_settings().max_repair_iterations)
    create_zip: bool = False


class Pipeline:
    """Encapsulates the full conveyor.

    Reusable: instantiate once, call `.generate(prompt)` many times. Each call
    creates a fresh AgentContext so memories don't leak between requests.
    """

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        retriever: HybridRetriever | None = None,
        registry: ClassnameRegistry | None = None,
        config: PipelineConfig | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self._llm = llm or get_llm_client()
        self._retriever = retriever or HybridRetriever()
        # Hydrate RAG from seed data on first boot — agents query it during
        # generation, so the store must not be empty. `bootstrap` itself is
        # idempotent (skips when the store is non-empty), but we wrap it
        # defensively so a bad seed file can't take down the API process.
        try:
            bootstrap(self._retriever.store)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rag_bootstrap_failed", error=str(exc))
        # Cache the registry seed files in raw form; `make_context` then
        # returns a *fresh* ClassnameRegistry per request so the `unknown`
        # set is request-scoped and concurrent /generate calls cannot leak
        # findings into each other.
        self._registry_template = registry or ClassnameRegistry.from_seed_files()
        self.orchestrator = OrchestratorAgent()
        self.narrative = NarrativeAgent()
        self.scripter = ScripterAgent()
        self.config_master = ConfigMasterAgent()
        self.qa = QAAgent()

    def make_context(self) -> AgentContext:
        # Per-request registry: the `unknown` set is mutable and gets
        # cleared via `take_unknowns()`; sharing one across concurrent
        # requests would race. The known classnames are copied — cheap
        # because they're a flat dict.
        registry = ClassnameRegistry(items=dict(self._registry_template.items))
        return AgentContext(
            llm=self._llm,
            retriever=self._retriever,
            registry=registry,
        )

    async def generate(self, prompt: str, *, bus=None) -> GenerationResult:
        # Drain once at the top-level entry so every LLM call in this run
        # (orchestrator + narrative + scripter repair passes + …) contributes
        # to the same usage snapshot.
        usage_accumulator.drain()
        ctx = self.make_context()
        if bus:
            await bus.publish("agent_started", agent="orchestrator")
        brief = await self.orchestrator.run(prompt, ctx)
        if bus:
            await bus.publish("agent_done", agent="orchestrator",
                              missions=len(brief.missions))
            await bus.publish("agent_started", agent="narrative")
        plan = await self.narrative.run(brief, ctx)
        if bus:
            await bus.publish("agent_done", agent="narrative",
                              states=sum(len(bp.fsm.states) for bp in plan.blueprints))
        return await self.generate_from_plan(plan, ctx=ctx, bus=bus, _fresh_usage=False)

    async def generate_from_brief(self, brief: CampaignBrief, *, bus=None) -> GenerationResult:
        usage_accumulator.drain()
        ctx = self.make_context()
        if bus:
            await bus.publish("agent_started", agent="narrative")
        plan = await self.narrative.run(brief, ctx)
        if bus:
            await bus.publish("agent_done", agent="narrative",
                              states=sum(len(bp.fsm.states) for bp in plan.blueprints))
        return await self.generate_from_plan(plan, ctx=ctx, bus=bus, _fresh_usage=False)

    async def generate_from_plan(
        self,
        plan: CampaignPlan,
        *,
        ctx: AgentContext | None = None,
        bus=None,
        _fresh_usage: bool = True,
    ) -> GenerationResult:
        # Deep-copy: ConfigMaster intentionally writes derived fields back
        # onto the blueprints, but the caller's plan should not be mutated
        # under their feet (especially across concurrent /refine requests).
        plan = plan.model_copy(deep=True)
        # Drain any usage from unrelated calls, but only when this is the
        # TOP entry point (i.e. called directly by /refine). Callers that
        # already drained pass _fresh_usage=False so we don't wipe the
        # narrative/orchestrator usage we just recorded.
        if _fresh_usage:
            usage_accumulator.drain()
        ctx = ctx or self.make_context()
        if bus:
            await bus.publish("agent_started", agent="config_master")

        config_files, mission_dirs = await self.config_master.run(plan, ctx)
        if bus:
            await bus.publish("agent_done", agent="config_master",
                              artifacts=len(config_files))
            await bus.publish("agent_started", agent="scripter",
                              missions=len(plan.blueprints))

        # Missions are independent → run scripter in parallel.
        import asyncio as _asyncio
        scripter_tasks = [
            self.scripter.run(bp, ctx, mission_dir=mission_dirs[i])
            for i, bp in enumerate(plan.blueprints)
        ]
        sqf_batches = await _asyncio.gather(*scripter_tasks)
        sqf_files: list[GeneratedArtifact] = [a for batch in sqf_batches for a in batch]
        artifacts = config_files + sqf_files
        if bus:
            await bus.publish("agent_done", agent="scripter",
                              artifacts=len(sqf_files))
            await bus.publish("agent_started", agent="qa")

        report = await self.qa.run(plan, artifacts, ctx, iteration=1)
        iteration = 1
        while not report.is_clean(strict=self.config.qa_strict) and iteration < self.config.max_iterations:
            iteration += 1
            if bus:
                await bus.publish("qa_iteration", iteration=iteration,
                                  errors=len(report.errors),
                                  warnings=len(report.warnings))
            artifacts = await self.scripter.repair(artifacts, report, ctx)
            report = await self.qa.run(plan, artifacts, ctx, iteration=iteration)
        if bus:
            await bus.publish("agent_done", agent="qa",
                              errors=len(report.errors),
                              warnings=len(report.warnings),
                              iterations=iteration)

        from ..arma.campaign import slugify
        out_path = package_campaign(
            artifacts,
            root=self.config.output_dir,
            name=slugify(plan.brief.name),
            create_zip=self.config.create_zip,
        )

        # Phase-A analyses. These feed the web UI and the /generate response
        # but do not block pipeline success — they are advisory layers.
        pacing = analyse_campaign(plan).to_dict()
        playtest = [r.to_dict() for r in playtest_campaign(plan)]
        usage = usage_accumulator.drain().to_dict()

        return GenerationResult(
            plan=plan,
            artifacts=artifacts,
            qa=report,
            output_path=str(out_path),
            iterations=iteration,
            pacing=pacing,
            playtest=playtest,
            usage=usage,
        )


async def run_generation(prompt: str, *, config: PipelineConfig | None = None) -> GenerationResult:
    pipe = Pipeline(config=config)
    return await pipe.generate(prompt)
