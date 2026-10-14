"""Design run endpoints: start, poll, result, files, DWG, renders."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from saudi_plot_api.dependencies import (
    CurrentSessionDep,
    DbDep,
    SettingsDep,
    TrustedOriginDep,
    owned_project,
    owned_run,
)
from saudi_plot_api.errors import ApiError
from saudi_plot_api.models import (
    DesignRun,
    DesignRunEvent,
    OutputFile,
    PresentationRender,
)
from saudi_plot_api.schemas import (
    DesignRunResponse,
    DesignRunResult,
    OutputFileResponse,
    RenderResponse,
)
from saudi_plot_api.services import dwg as dwg_service
from saudi_plot_api.services import runner, storage
from saudi_plot_api.services.render import attempt_presentation_render

router = APIRouter(prefix="/api/v1", tags=["design-runs"])


def _run_response(db: DbDep, run: DesignRun) -> DesignRunResponse:
    events = (
        db.execute(
            select(DesignRunEvent)
            .where(DesignRunEvent.run_id == run.id)
            .order_by(DesignRunEvent.seq)
        )
        .scalars()
        .all()
    )
    return DesignRunResponse(
        id=run.id,
        project_id=run.project_id,
        status=run.status,
        support_status=run.support_status,
        design_fingerprint=run.design_fingerprint,
        error_code=run.error_code,
        requested_at=run.requested_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        events=[
            {
                "seq": e.seq,
                "status": e.status,
                "message": e.message,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    )


@router.post(
    "/projects/{project_id}/design-runs",
    response_model=DesignRunResponse,
    status_code=202,
    dependencies=[TrustedOriginDep],
)
def start_run(
    project_id: str,
    request: Request,
    session: CurrentSessionDep,
    db: DbDep,
    settings: SettingsDep,
) -> DesignRunResponse:
    """Insert the run and hand it to the in-process executor; returns quickly
    with the run id so the frontend can poll real progress."""
    owned_project(db, session, project_id)
    run = DesignRun(project_id=project_id, status="preparing_inputs")
    db.add(run)
    db.commit()
    runner.submit_run(
        request.app.state.run_executor,
        request.app.state.session_factory,
        settings,
        run.id,
    )
    return _run_response(db, run)


@router.get("/design-runs/{run_id}", response_model=DesignRunResponse)
def read_run(run_id: str, session: CurrentSessionDep, db: DbDep) -> DesignRunResponse:
    return _run_response(db, owned_run(db, session, run_id))


@router.get("/design-runs/{run_id}/result", response_model=DesignRunResult)
def read_result(run_id: str, session: CurrentSessionDep, db: DbDep) -> DesignRunResult:
    run = owned_run(db, session, run_id)
    files = (
        db.execute(
            select(OutputFile).where(OutputFile.run_id == run.id).order_by(OutputFile.filename)
        )
        .scalars()
        .all()
    )
    completed_render = (
        db.execute(
            select(PresentationRender)
            .where(PresentationRender.run_id == run.id, PresentationRender.status == "completed")
            .order_by(PresentationRender.created_at.desc())
        )
        .scalars()
        .first()
    )
    render_url = (
        f"/api/v1/design-runs/{run.id}/presentation-render/image"
        if completed_render is not None
        else None
    )
    # Detect an in-progress render so the frontend can show a loading state
    # and poll rather than silently showing the static placeholder.
    render_pending = False
    if render_url is None:
        in_progress = (
            db.execute(
                select(PresentationRender)
                .where(
                    PresentationRender.run_id == run.id,
                    PresentationRender.status.in_(("pending", "generating")),
                )
                .order_by(PresentationRender.created_at.desc())
            )
            .scalars()
            .first()
        )
        render_pending = in_progress is not None
    return DesignRunResult(
        id=run.id,
        project_id=run.project_id,
        status=run.status,
        support_status=run.support_status,
        design_fingerprint=run.design_fingerprint,
        assumptions=json.loads(run.assumptions_json) if run.assumptions_json else [],
        unapplied_answers=(
            json.loads(run.unapplied_answers_json) if run.unapplied_answers_json else []
        ),
        unsupported_requirements=(json.loads(run.unsupported_json) if run.unsupported_json else []),
        character=json.loads(run.character_json) if run.character_json else None,
        engine_summary=json.loads(run.engine_summary_json) if run.engine_summary_json else None,
        files=[OutputFileResponse.model_validate(f) for f in files],
        presentation_render_url=render_url,
        render_pending=render_pending,
    )


def _owned_file(db: DbDep, session: CurrentSessionDep, run_id: str, file_id: str) -> OutputFile:
    run = owned_run(db, session, run_id)
    record = db.execute(
        select(OutputFile).where(OutputFile.id == file_id, OutputFile.run_id == run.id)
    ).scalar_one_or_none()
    if record is None:
        raise ApiError(404, "file_not_found", "The file does not exist.")
    return record


@router.get("/design-runs/{run_id}/files/{file_id}")
def download_file(
    run_id: str, file_id: str, session: CurrentSessionDep, db: DbDep, settings: SettingsDep
) -> FileResponse:
    record = _owned_file(db, session, run_id, file_id)
    path = storage.resolve_relative(settings.storage_root, record.relative_path)
    if not path.is_file():
        raise ApiError(404, "file_not_found", "The file does not exist.")
    return FileResponse(path, media_type=record.content_type, filename=record.filename)


@router.get("/design-runs/{run_id}/dwg")
def download_dwg(
    run_id: str, session: CurrentSessionDep, db: DbDep, settings: SettingsDep
) -> FileResponse:
    """Real DWG conversion of the run's DXF via an installed converter.

    Without a legitimate converter this is a structured 501 -- a DXF is never
    renamed to DWG."""
    run = owned_run(db, session, run_id)
    dxf = db.execute(
        select(OutputFile).where(OutputFile.run_id == run.id, OutputFile.kind == "dxf")
    ).scalar_one_or_none()
    if dxf is None:
        raise ApiError(404, "file_not_found", "The run has no DXF output.")
    try:
        dxf_path = storage.resolve_relative(settings.storage_root, dxf.relative_path)
        produced = dwg_service.convert_dxf_to_dwg(dxf_path, dxf_path.parent / "dwg")
    except dwg_service.DwgUnavailable as unavailable:
        raise ApiError(
            501,
            "dwg_converter_unavailable",
            "No DWG converter is installed on the server.",
            {"required_dependency": str(unavailable)},
        ) from unavailable
    except dwg_service.DwgConversionFailed as failed:
        raise ApiError(502, "dwg_conversion_failed", str(failed)) from failed
    digest, size = storage.file_digest(produced)
    return FileResponse(
        produced,
        media_type="image/vnd.dwg",
        filename=produced.name,
        headers={"X-Content-SHA256": digest, "X-Content-Length-Bytes": str(size)},
    )


@router.post(
    "/design-runs/{run_id}/presentation-render",
    response_model=RenderResponse,
    dependencies=[TrustedOriginDep],
)
def create_render(
    run_id: str, session: CurrentSessionDep, db: DbDep, settings: SettingsDep
) -> RenderResponse:
    run = owned_run(db, session, run_id)
    if run.status not in ("completed", "completed_with_assumptions"):
        raise ApiError(
            409, "run_not_completed", "The design run has no completed engineering result yet."
        )
    plan = db.execute(
        select(OutputFile).where(OutputFile.run_id == run.id, OutputFile.kind == "svg_plan")
    ).scalar_one_or_none()
    render = attempt_presentation_render(db, settings, run, plan.relative_path if plan else None)
    return RenderResponse.model_validate(render)


@router.get("/design-runs/{run_id}/presentation-render", response_model=RenderResponse)
def read_render(run_id: str, session: CurrentSessionDep, db: DbDep) -> RenderResponse:
    run = owned_run(db, session, run_id)
    render = (
        db.execute(
            select(PresentationRender)
            .where(PresentationRender.run_id == run.id)
            .order_by(PresentationRender.created_at.desc())
        )
        .scalars()
        .first()
    )
    if render is None:
        raise ApiError(404, "render_not_found", "No presentation render exists for this run.")
    return RenderResponse.model_validate(render)


@router.get("/design-runs/{run_id}/presentation-render/image")
def render_image(
    run_id: str, session: CurrentSessionDep, db: DbDep, settings: SettingsDep
) -> FileResponse:
    run = owned_run(db, session, run_id)
    render = (
        db.execute(
            select(PresentationRender)
            .where(PresentationRender.run_id == run.id, PresentationRender.status == "completed")
            .order_by(PresentationRender.created_at.desc())
        )
        .scalars()
        .first()
    )
    if render is None or not render.relative_path:
        raise ApiError(404, "render_not_found", "No completed presentation render exists.")
    path = storage.resolve_relative(settings.storage_root, render.relative_path)
    if not path.is_file():
        raise ApiError(404, "render_not_found", "No completed presentation render exists.")
    return FileResponse(path, media_type=render.content_type or "image/png")
