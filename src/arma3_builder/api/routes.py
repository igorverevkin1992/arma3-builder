"""FastAPI router — core + template + refinement + SSE surfaces."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ..arma.fsm import diagram_for_blueprint
from ..arma.launcher import build_launch_payload
from ..pipeline import Pipeline, PipelineConfig
from ..pipeline.diff import diff_artifacts
from ..pipeline.refine import refine_plan
from ..protocols import CampaignBrief, CampaignPlan, MissionBlueprint
from ..qa.score import score_campaign
from ..templates import get_template, list_templates
from .events import EventBus
from .schemas import (
    GenerateRequest,
    GenerateResponse,
    PreviewResponse,
    RefineRequest,
    TemplateInstance,
)

router = APIRouter(prefix="", tags=["arma3-builder"])

_pipeline = Pipeline()
_last_run_cache: dict[str, list] = {}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "arma3-builder"}


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    pipe = _pipeline
    if req.create_zip:
        cfg = PipelineConfig(create_zip=True)
        pipe = Pipeline(config=cfg)
    if req.brief is not None:
        result = await pipe.generate_from_brief(req.brief)
    elif req.prompt:
        result = await pipe.generate(req.prompt)
    else:
        raise HTTPException(status_code=400, detail="prompt or brief required")

    _last_run_cache["artifacts"] = result.artifacts
    _last_run_cache["plan"] = result.plan

    score = score_campaign(result.plan, result.qa)
    first = result.plan.blueprints[0] if result.plan.blueprints else None
    launch = build_launch_payload(
        Path(result.output_path or "."),
        world=first.brief.map if first else "VR",
        slug=result.output_path.split("/")[-1] if result.output_path else "",
        mods=result.plan.brief.mods,
    )

    return GenerateResponse(
        output_path=result.output_path,
        iterations=result.iterations,
        qa=result.qa,
        artifact_count=len(result.artifacts),
        plan=result.plan,
        score=score.to_dict(),
        launch=launch,
    )


@router.post("/generate/stream")
async def generate_stream(req: GenerateRequest) -> StreamingResponse:
    bus = EventBus()

    async def run() -> None:
        try:
            if req.brief is not None:
                result = await _pipeline.generate_from_brief(req.brief, bus=bus)
            elif req.prompt:
                result = await _pipeline.generate(req.prompt, bus=bus)
            else:
                await bus.publish("error", message="prompt or brief required")
                await bus.finish()
                return
            _last_run_cache["artifacts"] = result.artifacts
            _last_run_cache["plan"] = result.plan
            await bus.publish(
                "done",
                output_path=result.output_path,
                artifact_count=len(result.artifacts),
                errors=len(result.qa.errors),
                warnings=len(result.qa.warnings),
                score=score_campaign(result.plan, result.qa).to_dict(),
                plan=result.plan.model_dump(mode="json"),
            )
        except Exception as exc:  # noqa: BLE001
            await bus.publish("error", message=str(exc))
        finally:
            await bus.finish()

    asyncio.create_task(run())
    return StreamingResponse(bus.stream(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
# Preview & diagrams (Phase 4 node editor)
# --------------------------------------------------------------------------- #


@router.post("/preview", response_model=PreviewResponse)
async def preview(req: GenerateRequest) -> PreviewResponse:
    if req.brief is not None:
        ctx = _pipeline.make_context()
        plan = await _pipeline.narrative.run(req.brief, ctx)
    elif req.prompt:
        ctx = _pipeline.make_context()
        brief = await _pipeline.orchestrator.run(req.prompt, ctx)
        plan = await _pipeline.narrative.run(brief, ctx)
    else:
        raise HTTPException(status_code=400, detail="prompt or brief required")

    diagrams = [diagram_for_blueprint(bp) for bp in plan.blueprints]
    return PreviewResponse(plan=plan, fsm_diagrams=diagrams)


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #


@router.get("/templates")
async def templates_list() -> list[dict[str, Any]]:
    return [
        {
            "id": t.id,
            "label": t.label,
            "summary": t.summary,
            "tags": t.tags,
            "parameters": [
                {
                    "name": p.name, "label": p.label, "kind": p.kind,
                    "default": p.default, "required": p.required,
                }
                for p in t.parameters
            ],
        }
        for t in list_templates()
    ]


@router.post("/templates/{template_id}/instantiate", response_model=TemplateInstance)
async def templates_instantiate(template_id: str, params: dict[str, Any]) -> TemplateInstance:
    try:
        tpl = get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    blueprint = tpl.instantiate(params)
    return TemplateInstance(blueprint=blueprint)


# --------------------------------------------------------------------------- #
# Refinement (conversational follow-up)
# --------------------------------------------------------------------------- #


@router.post("/refine", response_model=GenerateResponse)
async def refine(req: RefineRequest) -> GenerateResponse:
    llm = _pipeline._llm
    plan = await refine_plan(
        req.plan, req.instruction,
        llm=llm, model=_pipeline.narrative.model,
    )
    result = await _pipeline.generate_from_plan(plan)

    # Produce a diff view against the previous run if we have one.
    previous = _last_run_cache.get("artifacts", [])
    diff = diff_artifacts(previous, result.artifacts)
    _last_run_cache["artifacts"] = result.artifacts
    _last_run_cache["plan"] = result.plan

    score = score_campaign(result.plan, result.qa)
    first = result.plan.blueprints[0] if result.plan.blueprints else None
    launch = build_launch_payload(
        Path(result.output_path or "."),
        world=first.brief.map if first else "VR",
        slug=result.output_path.split("/")[-1] if result.output_path else "",
        mods=result.plan.brief.mods,
    )
    return GenerateResponse(
        output_path=result.output_path,
        iterations=result.iterations,
        qa=result.qa,
        artifact_count=len(result.artifacts),
        plan=result.plan,
        score=score.to_dict(),
        launch=launch,
        diff=[{"path": d.path, "change": d.change, "unified": d.unified} for d in diff],
    )


# --------------------------------------------------------------------------- #
# Web UI (single-page static)
# --------------------------------------------------------------------------- #


_WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@router.get("/")
async def ui_root() -> FileResponse:
    index = _WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="UI not built")
    return FileResponse(index, media_type="text/html")


@router.get("/ui/{asset:path}")
async def ui_asset(asset: str) -> FileResponse:
    path = _WEB_DIR / asset
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(path)
