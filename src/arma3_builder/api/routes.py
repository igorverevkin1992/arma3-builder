"""FastAPI router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..arma.fsm import diagram_for_blueprint
from ..pipeline import Pipeline, PipelineConfig
from .schemas import GenerateRequest, GenerateResponse, PreviewResponse

router = APIRouter(prefix="", tags=["arma3-builder"])

_pipeline = Pipeline()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "arma3-builder"}


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    cfg = PipelineConfig(create_zip=req.create_zip)
    pipe = Pipeline(config=cfg) if cfg.create_zip else _pipeline
    if req.brief is not None:
        result = await pipe.generate_from_brief(req.brief)
    elif req.prompt:
        result = await pipe.generate(req.prompt)
    else:  # pragma: no cover — schema enforces this
        raise HTTPException(status_code=400, detail="prompt or brief required")
    return GenerateResponse(
        output_path=result.output_path,
        iterations=result.iterations,
        qa=result.qa,
        artifact_count=len(result.artifacts),
        plan=result.plan,
    )


@router.post("/preview", response_model=PreviewResponse)
async def preview(req: GenerateRequest) -> PreviewResponse:
    """Returns the FSM graphs for the visual editor without writing files."""
    if req.brief is not None:
        ctx = _pipeline.make_context()
        plan = await _pipeline.narrative.run(req.brief, ctx)
    elif req.prompt:
        ctx = _pipeline.make_context()
        brief = await _pipeline.orchestrator.run(req.prompt, ctx)
        plan = await _pipeline.narrative.run(brief, ctx)
    else:  # pragma: no cover
        raise HTTPException(status_code=400, detail="prompt or brief required")

    diagrams = [diagram_for_blueprint(bp) for bp in plan.blueprints]
    return PreviewResponse(plan=plan, fsm_diagrams=diagrams)
