"""FastAPI router — core + template + refinement + SSE surfaces."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from ..arma.fsm import diagram_for_blueprint
from ..arma.launcher import build_launch_payload
from ..pipeline import Pipeline, PipelineConfig
from ..pipeline.diff import diff_artifacts
from ..pipeline.refine import refine_plan
from ..qa.score import score_campaign
from ..templates import get_template, list_templates
from .events import EventBus
from .schemas import (
    GenerateRequest,
    GenerateResponse,
    PlanUpdateRequest,
    PreviewResponse,
    RefineRequest,
    SyncFromEdenRequest,
    TemplateInstance,
)

router = APIRouter(prefix="", tags=["arma3-builder"])

_pipeline = Pipeline()


# Per-session run cache keyed by `X-Session-Id` header (UI sends it). Falls
# back to a single global slot for backwards-compat curl users — that path
# is documented as not safe for concurrent calls.
#
# Bounded LRU to prevent unbounded memory growth: clients can otherwise
# allocate arbitrary slots by varying the X-Session-Id header.
_SESSION_CACHE_MAX = 64
_session_runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
_DEFAULT_SESSION = "_default"


def _session_key(req_headers: dict[str, str] | None = None) -> str:
    if req_headers:
        sid = req_headers.get("x-session-id") or req_headers.get("X-Session-Id")
        if sid:
            return sid
    return _DEFAULT_SESSION


def _store_run(session: str, *, plan, artifacts) -> None:
    _session_runs[session] = {"plan": plan, "artifacts": artifacts}
    _session_runs.move_to_end(session)
    while len(_session_runs) > _SESSION_CACHE_MAX:
        _session_runs.popitem(last=False)


def _previous_run(session: str) -> dict[str, Any]:
    run = _session_runs.get(session)
    if run is not None:
        _session_runs.move_to_end(session)
        return run
    return {}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "arma3-builder"}


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest, request: Request) -> GenerateResponse:
    # Reuse the singleton when possible — bootstrap is expensive. Construct a
    # one-off Pipeline only for the rare zip path so the singleton's default
    # config (no zip) isn't perturbed by a concurrent caller.
    pipe = _pipeline
    if req.create_zip:
        pipe = Pipeline(config=PipelineConfig(create_zip=True),
                        retriever=_pipeline._retriever,
                        registry=_pipeline._registry_template,
                        llm=_pipeline._llm)
    if req.brief is not None:
        result = await pipe.generate_from_brief(req.brief)
    elif req.prompt:
        result = await pipe.generate(req.prompt)
    else:
        raise HTTPException(status_code=400, detail="prompt or brief required")

    session = _session_key(dict(request.headers))
    _store_run(session, plan=result.plan, artifacts=result.artifacts)

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
        pacing=result.pacing,
        playtest=result.playtest,
        usage=result.usage,
        critic_notes=result.critic_notes,
    )


@router.post("/generate/stream")
async def generate_stream(req: GenerateRequest, request: Request) -> StreamingResponse:
    bus = EventBus()
    session = _session_key(dict(request.headers))

    async def run() -> None:
        try:
            if req.brief is not None:
                result = await _pipeline.generate_from_brief(req.brief, bus=bus)
            elif req.prompt:
                result = await _pipeline.generate(req.prompt, bus=bus)
            else:
                await bus.publish("error", message="prompt or brief required")
                return
            _store_run(session, plan=result.plan, artifacts=result.artifacts)
            await bus.publish(
                "done",
                output_path=result.output_path,
                artifact_count=len(result.artifacts),
                errors=len(result.qa.errors),
                warnings=len(result.qa.warnings),
                score=score_campaign(result.plan, result.qa).to_dict(),
                plan=result.plan.model_dump(mode="json"),
                pacing=result.pacing,
                playtest=result.playtest,
                usage=result.usage,
                critic_notes=result.critic_notes,
            )
        except asyncio.CancelledError:
            # Client disconnected — propagate so the task tree shuts down.
            raise
        except Exception as exc:  # noqa: BLE001
            await bus.publish("error", message=str(exc))
        finally:
            await bus.finish()

    task = asyncio.create_task(run())

    async def streamer() -> Any:
        try:
            async for chunk in bus.stream():
                yield chunk
        finally:
            # Ensures the background task is collected if the client closes
            # the SSE early (browser tab closed, network drop, ...).
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001
                    # Cleanup-time errors must not propagate (the response is
                    # already gone), but they shouldn't be silently swallowed.
                    import logging
                    logging.getLogger(__name__).exception(
                        "Background SSE task raised during cleanup"
                    )

    return StreamingResponse(streamer(), media_type="text/event-stream")


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
async def refine(req: RefineRequest, request: Request) -> GenerateResponse:
    llm = _pipeline._llm
    plan = await refine_plan(
        req.plan, req.instruction,
        llm=llm, model=_pipeline.narrative.model,
    )
    result = await _pipeline.generate_from_plan(plan)

    # Per-session diff so concurrent refines don't pollute each other's
    # "before" snapshot.
    session = _session_key(dict(request.headers))
    previous = _previous_run(session).get("artifacts", [])
    diff = diff_artifacts(previous, result.artifacts)
    _store_run(session, plan=result.plan, artifacts=result.artifacts)

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
        pacing=result.pacing,
        playtest=result.playtest,
        usage=result.usage,
        critic_notes=result.critic_notes,
    )


# --------------------------------------------------------------------------- #
# Phase C — plan update + Eden sync + standalone critique
# --------------------------------------------------------------------------- #


@router.post("/plan/update", response_model=GenerateResponse)
async def plan_update(req: PlanUpdateRequest, request: Request) -> GenerateResponse:
    """Accept a user-edited CampaignPlan (e.g. FSM tweaks from the web UI)
    and optionally regenerate artefacts from it. No LLM involvement."""
    if not req.regenerate:
        # Just echo the plan back so the UI can confirm validity without
        # paying the generate-and-package cost.
        from ..protocols import QAReport
        return GenerateResponse(
            output_path=None, iterations=0,
            qa=QAReport(),
            artifact_count=0,
            plan=req.plan,
        )
    result = await _pipeline.generate_from_plan(req.plan)
    session = _session_key(dict(request.headers))
    _store_run(session, plan=result.plan, artifacts=result.artifacts)
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
        score=score_campaign(result.plan, result.qa).to_dict(),
        launch=launch,
        pacing=result.pacing,
        playtest=result.playtest,
        usage=result.usage,
        critic_notes=result.critic_notes,
    )


@router.post("/sync-from-eden", response_model=GenerateResponse)
async def sync_from_eden(req: SyncFromEdenRequest, request: Request) -> GenerateResponse:
    """Merge Eden-edited ``mission.sqm`` back onto a mission blueprint."""
    from ..arma.sqm_import import sync_into_blueprint

    if req.mission_index < 0 or req.mission_index >= len(req.plan.blueprints):
        raise HTTPException(status_code=400, detail="mission_index out of range")
    new_plan = req.plan.model_copy(deep=True)
    new_plan.blueprints[req.mission_index] = sync_into_blueprint(
        new_plan.blueprints[req.mission_index], req.sqm_text
    )
    # Regenerate downstream artefacts so the user sees the edit take effect.
    result = await _pipeline.generate_from_plan(new_plan)
    session = _session_key(dict(request.headers))
    _store_run(session, plan=result.plan, artifacts=result.artifacts)
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
        score=score_campaign(result.plan, result.qa).to_dict(),
        launch=launch,
        pacing=result.pacing,
        playtest=result.playtest,
        usage=result.usage,
        critic_notes=result.critic_notes,
    )


@router.post("/critique")
async def critique(req: RefineRequest) -> dict[str, Any]:
    """Standalone Critic pass on an existing plan, no regeneration."""
    ctx = _pipeline.make_context()
    notes = await _pipeline.critic.run(req.plan, ctx)
    return {"notes": [n.model_dump() for n in notes]}


# --------------------------------------------------------------------------- #
# File browser — let the UI introspect generated artefacts on disk.
# --------------------------------------------------------------------------- #


def _safe_output_path(rel: str) -> Path:
    """Resolve `rel` under the configured output dir, blocking traversal.

    The output directory is itself canonicalised; any path that escapes is
    rejected with HTTP 403. Returns the resolved Path on success.
    """
    from ..config import get_settings

    base = Path(get_settings().output_dir).resolve()
    candidate = (base / rel).resolve() if rel else base
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path traversal blocked") from exc
    return candidate


@router.get("/files/list")
async def files_list(rel: str = Query(default="")) -> dict[str, Any]:
    """List directory contents under the output tree.

    Returns directories first, then files, each with `name`, `path` (relative
    to output_dir), `kind` ("dir"|"file"), and `size` for files.

    Race-tolerant: if the directory or a child disappears between the listing
    and the per-entry stat, we drop that entry rather than crashing.
    """
    target = _safe_output_path(rel)
    from ..config import get_settings
    base = Path(get_settings().output_dir).resolve()

    try:
        children = sorted(
            target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
    except FileNotFoundError:
        return {"path": rel, "entries": []}
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail="not a directory") from exc

    out: list[dict[str, Any]] = []
    for child in children:
        try:
            is_dir = child.is_dir()
            size = child.stat().st_size if not is_dir else None
        except (FileNotFoundError, PermissionError):
            continue
        out.append({
            "name": child.name,
            "path": str(child.relative_to(base)),
            "kind": "dir" if is_dir else "file",
            "size": size,
        })
    return {"path": rel, "entries": out}


@router.get("/files/read", response_class=PlainTextResponse)
async def files_read(rel: str = Query(...)) -> str:
    """Return the contents of a file under the output tree.

    Caps at 256 KB so the UI doesn't blow up on giant binaries; larger
    files return a placeholder describing the size and pointing the user
    at the absolute path. Reads the file in one syscall sequence to avoid
    TOCTOU between stat and read.
    """
    target = _safe_output_path(rel)
    cap = 256 * 1024
    try:
        size = target.stat().st_size
        if not target.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        if size > cap:
            return (
                f"// File too large to render in the UI ({size} bytes).\n"
                f"// Open it locally at: {target}\n"
            )
        return target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="permission denied") from exc
    except UnicodeDecodeError:
        return f"// Binary file ({size} bytes) — open with an external tool.\n"


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


_WEB_DIR_RESOLVED = _WEB_DIR.resolve()


@router.get("/ui/{asset:path}")
async def ui_asset(asset: str) -> FileResponse:
    """Serve a file from `web/` after explicit traversal protection.

    `Path(_WEB_DIR) / asset` does NOT canonicalise — `..` segments would
    walk out of the web directory. We resolve and verify containment.
    """
    candidate = (_WEB_DIR / asset).resolve()
    try:
        candidate.relative_to(_WEB_DIR_RESOLVED)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path traversal blocked") from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(candidate)
