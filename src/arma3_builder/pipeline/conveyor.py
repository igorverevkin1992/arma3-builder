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
from ..llm import LLMClient, get_llm_client
from ..protocols import (
    CampaignBrief,
    CampaignPlan,
    GeneratedArtifact,
    GenerationResult,
)
from ..rag import HybridRetriever
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
        self._registry = registry or ClassnameRegistry.from_seed_files()
        self.orchestrator = OrchestratorAgent()
        self.narrative = NarrativeAgent()
        self.scripter = ScripterAgent()
        self.config_master = ConfigMasterAgent()
        self.qa = QAAgent()

    def make_context(self) -> AgentContext:
        return AgentContext(
            llm=self._llm,
            retriever=self._retriever,
            registry=self._registry,
        )

    async def generate(self, prompt: str) -> GenerationResult:
        ctx = self.make_context()

        brief = await self.orchestrator.run(prompt, ctx)
        plan = await self.narrative.run(brief, ctx)
        return await self.generate_from_plan(plan, ctx=ctx)

    async def generate_from_brief(self, brief: CampaignBrief) -> GenerationResult:
        ctx = self.make_context()
        plan = await self.narrative.run(brief, ctx)
        return await self.generate_from_plan(plan, ctx=ctx)

    async def generate_from_plan(
        self,
        plan: CampaignPlan,
        *,
        ctx: AgentContext | None = None,
    ) -> GenerationResult:
        ctx = ctx or self.make_context()

        config_files, mission_dirs = await self.config_master.run(plan, ctx)
        sqf_files: list[GeneratedArtifact] = []
        for i, blueprint in enumerate(plan.blueprints):
            sqf_files.extend(
                await self.scripter.run(blueprint, ctx, mission_dir=mission_dirs[i])
            )
        artifacts = config_files + sqf_files

        report = await self.qa.run(plan, artifacts, ctx, iteration=1)
        iteration = 1
        while not report.is_clean(strict=self.config.qa_strict) and iteration < self.config.max_iterations:
            iteration += 1
            artifacts = await self.scripter.repair(artifacts, report, ctx)
            report = await self.qa.run(plan, artifacts, ctx, iteration=iteration)

        from ..arma.campaign import slugify
        out_path = package_campaign(
            artifacts,
            root=self.config.output_dir,
            name=slugify(plan.brief.name),
            create_zip=self.config.create_zip,
        )

        return GenerationResult(
            plan=plan,
            artifacts=artifacts,
            qa=report,
            output_path=str(out_path),
            iterations=iteration,
        )


async def run_generation(prompt: str, *, config: PipelineConfig | None = None) -> GenerationResult:
    pipe = Pipeline(config=config)
    return await pipe.generate(prompt)
