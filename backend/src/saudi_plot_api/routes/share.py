"""Expiring, unguessable, read-only share links.

A share link exposes ONLY sanitized design outputs of the project's latest
completed run: support status, assumptions, quality summary, and files marked
shareable (coordinate-free DXF and SVG artifacts) plus a completed
presentation render. It never exposes deed documents, owner information,
coordinates (the location-stamped PDFs stay private), session data, private
paths, API keys, or internal errors.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy import select

from saudi_plot_api.database import utcnow
from saudi_plot_api.dependencies import (
    CurrentSessionDep,
    DbDep,
    SettingsDep,
    TrustedOriginDep,
    owned_project,
)
from saudi_plot_api.errors import ApiError
from saudi_plot_api.models import (
    DesignRun,
    OutputFile,
    PresentationRender,
    ShareToken,
)
from saudi_plot_api.schemas import ShareResponse

router = APIRouter(prefix="/api/v1", tags=["share"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@router.post(
    "/projects/{project_id}/share",
    response_model=ShareResponse,
    status_code=201,
    dependencies=[TrustedOriginDep],
)
def create_share(
    project_id: str, session: CurrentSessionDep, db: DbDep, settings: SettingsDep
) -> ShareResponse:
    owned_project(db, session, project_id)
    latest = _latest_completed_run(db, project_id)
    if latest is None:
        raise ApiError(409, "no_completed_run", "The project has no completed design run to share.")
    token = secrets.token_urlsafe(32)
    record = ShareToken(
        project_id=project_id,
        token_hash=_hash(token),
        expires_at=utcnow() + timedelta(seconds=settings.share_ttl_seconds),
    )
    db.add(record)
    db.commit()
    return ShareResponse(
        share_token=token,
        expires_at=record.expires_at,
        url_path=f"/api/v1/shared/{token}",
    )


def _latest_completed_run(db: DbDep, project_id: str) -> DesignRun | None:
    return (
        db.execute(
            select(DesignRun)
            .where(
                DesignRun.project_id == project_id,
                DesignRun.status.in_(("completed", "completed_with_assumptions")),
            )
            .order_by(DesignRun.requested_at.desc())
        )
        .scalars()
        .first()
    )


def _valid_share(db: DbDep, share_token: str) -> ShareToken:
    record = db.execute(
        select(ShareToken).where(ShareToken.token_hash == _hash(share_token))
    ).scalar_one_or_none()
    if record is None or record.revoked or record.expires_at <= utcnow():
        # Expired, revoked, and unknown tokens are indistinguishable.
        raise ApiError(404, "share_not_found", "The share link does not exist or has expired.")
    return record


@router.get("/shared/{share_token}")
def read_shared(share_token: str, db: DbDep) -> dict:
    """Public sanitized view -- no session required, nothing private inside."""
    record = _valid_share(db, share_token)
    run = _latest_completed_run(db, record.project_id)
    if run is None:
        raise ApiError(404, "share_not_found", "The share link does not exist or has expired.")
    files = (
        db.execute(
            select(OutputFile).where(OutputFile.run_id == run.id, OutputFile.shareable.is_(True))
        )
        .scalars()
        .all()
    )
    render = (
        db.execute(
            select(PresentationRender)
            .where(PresentationRender.run_id == run.id, PresentationRender.status == "completed")
            .order_by(PresentationRender.created_at.desc())
        )
        .scalars()
        .first()
    )
    summary = json.loads(run.engine_summary_json) if run.engine_summary_json else None
    return {
        "kind": "shared_design_result",
        "status": run.status,
        "support_status": run.support_status,
        "design_fingerprint": run.design_fingerprint,
        "assumptions": json.loads(run.assumptions_json) if run.assumptions_json else [],
        "engine_summary": summary,
        "files": [
            {
                "id": f.id,
                "kind": f.kind,
                "filename": f.filename,
                "content_type": f.content_type,
                "size_bytes": f.size_bytes,
                "sha256": f.sha256,
                "url_path": f"/api/v1/shared/{share_token}/files/{f.id}",
            }
            for f in files
        ],
        "presentation_render": (
            {"url_path": f"/api/v1/shared/{share_token}/render"} if render else None
        ),
        "expires_at": record.expires_at.isoformat(),
        "disclaimer": (
            "Concept design produced with demo-provenance reference data; not an "
            "official or regulatory document."
        ),
    }


@router.get("/shared/{share_token}/files/{file_id}")
def shared_file(share_token: str, file_id: str, db: DbDep, settings: SettingsDep) -> FileResponse:
    from saudi_plot_api.services import storage

    record = _valid_share(db, share_token)
    run = _latest_completed_run(db, record.project_id)
    if run is None:
        raise ApiError(404, "share_not_found", "The share link does not exist or has expired.")
    file_record = db.execute(
        select(OutputFile).where(
            OutputFile.id == file_id,
            OutputFile.run_id == run.id,
            OutputFile.shareable.is_(True),
        )
    ).scalar_one_or_none()
    if file_record is None:
        raise ApiError(404, "file_not_found", "The file does not exist.")
    path = storage.resolve_relative(settings.storage_root, file_record.relative_path)
    if not path.is_file():
        raise ApiError(404, "file_not_found", "The file does not exist.")
    return FileResponse(path, media_type=file_record.content_type, filename=file_record.filename)


@router.get("/shared/{share_token}/render")
def shared_render(share_token: str, db: DbDep, settings: SettingsDep) -> FileResponse:
    from saudi_plot_api.services import storage

    record = _valid_share(db, share_token)
    run = _latest_completed_run(db, record.project_id)
    render = (
        db.execute(
            select(PresentationRender)
            .where(PresentationRender.run_id == run.id, PresentationRender.status == "completed")
            .order_by(PresentationRender.created_at.desc())
        )
        .scalars()
        .first()
        if run
        else None
    )
    if render is None or not render.relative_path:
        raise ApiError(404, "render_not_found", "No presentation render is shared.")
    path = storage.resolve_relative(settings.storage_root, render.relative_path)
    if not path.is_file():
        raise ApiError(404, "render_not_found", "No presentation render is shared.")
    return FileResponse(path, media_type=render.content_type or "image/png")
