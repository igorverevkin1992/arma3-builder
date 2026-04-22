"""Command-line entrypoint."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .pipeline import Pipeline, PipelineConfig
from .protocols import CampaignBrief


def _load_brief(path: Path) -> CampaignBrief:
    return CampaignBrief.model_validate_json(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arma3-builder")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Generate a campaign from a prompt or brief file")
    src = g.add_mutually_exclusive_group(required=True)
    src.add_argument("--prompt", type=str)
    src.add_argument("--brief", type=Path, help="Path to a CampaignBrief JSON")
    g.add_argument("--output", type=Path, default=None)
    g.add_argument("--zip", action="store_true")
    g.add_argument("--no-strict", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        cfg = PipelineConfig(create_zip=args.zip)
        if args.output:
            cfg.output_dir = args.output
        if args.no_strict:
            cfg.qa_strict = False
        pipe = Pipeline(config=cfg)
        if args.brief:
            brief = _load_brief(args.brief)
            result = asyncio.run(pipe.generate_from_brief(brief))
        else:
            result = asyncio.run(pipe.generate(args.prompt))
        print(json.dumps({
            "output_path": result.output_path,
            "iterations": result.iterations,
            "errors": [f.model_dump() for f in result.qa.errors],
            "warnings": [f.model_dump() for f in result.qa.warnings],
            "artifact_count": len(result.artifacts),
        }, indent=2))
        return 0 if result.qa.is_clean(strict=cfg.qa_strict) else 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
