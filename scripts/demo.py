#!/usr/bin/env python3
"""Run the pipeline against the bundled sample brief.

Uses the stub LLM provider by default — no API keys required. Output is
written to ``./output/operation_silent_reaper/``.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Allow running from a checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arma3_builder.pipeline import Pipeline, PipelineConfig
from arma3_builder.protocols import CampaignBrief


async def main() -> None:
    brief_path = Path(__file__).resolve().parents[1] / "examples" / "sample_brief.json"
    brief = CampaignBrief.model_validate_json(brief_path.read_text(encoding="utf-8"))

    pipe = Pipeline(config=PipelineConfig(qa_strict=False))
    result = await pipe.generate_from_brief(brief)

    print(json.dumps({
        "output_path": result.output_path,
        "iterations": result.iterations,
        "artifact_count": len(result.artifacts),
        "errors": [f.model_dump() for f in result.qa.errors],
        "warnings": [f.model_dump() for f in result.qa.warnings],
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
