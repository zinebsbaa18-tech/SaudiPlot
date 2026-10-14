"""FastAPI dependencies: settings, database session, current anonymous session.

The engine and session factory live on ``app.state`` (set by ``main.create_app``)
so tests can build isolated apps without global mutable state.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from saudi_plot_api.config import Settings
from saudi_plot_api.errors import ApiError
from saudi_plot_api.models import AnonymousSession
from saudi_plot_api.services.sessions import SessionResolution, resolve_session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


def enforce_trusted_origin(request: Request, settings: SettingsDep) -> None:
    """CSRF guard for state-changing endpoints.

    A cross-site top-level form POST bypasses CORS (navigations are never
    preflighted), so browser-sent ``Origin``/``Referer`` must match either the
    API itself or a configured frontend origin. Requests without either header
    (non-browser clients) pass through.

    In development the check is skipped: the Vite dev-server proxy sits in
    front of the API and rewrites the Origin, but the underlying Replit
    reverse-proxy infrastructure can forward a *.replit.dev Origin that would
    otherwise fail the allow-list. CSRF protection is enforced in production
    where ``SPD_ENVIRONMENT=production`` is required.
    """
    if settings.environment == "development":
        return
    source = request.headers.get("origin") or request.headers.get("referer")
    if source is None:
        return
    parts = urlsplit(source)
    source_origin = f"{parts.scheme}://{parts.netloc}"
    allowed = set(settings.cors_origins)
    allowed.add(f"{request.url.scheme}://{request.url.netloc}")
    if source_origin not in allowed:
        raise ApiError(403, "origin_not_allowed", "Cross-site requests are not allowed.")


TrustedOriginDep = Depends(enforce_trusted_origin)


def get_current_session(request: Request, settings: SettingsDep, db: DbDep) -> AnonymousSession:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise ApiError(401, "session_required", "No active session. Create one first.")

    session, resolution = resolve_session(db, token)
    if resolution is SessionResolution.EXPIRED:
        raise ApiError(401, "session_expired", "The session has expired. Create a new one.")
    if session is None:
        raise ApiError(401, "session_invalid", "The session is not valid. Create a new one.")
    return session


CurrentSessionDep = Annotated[AnonymousSession, Depends(get_current_session)]


def owned_project(db: Session, session: AnonymousSession, project_id: str):
    """The project, if it belongs to the current session -- otherwise 404.

    Cross-session access is indistinguishable from a missing project, so
    existence is never leaked.
    """
    from saudi_plot_api.models import Project
    from sqlalchemy import select

    project = db.execute(
        select(Project).where(Project.id == project_id, Project.session_id == session.id)
    ).scalar_one_or_none()
    if project is None:
        raise ApiError(404, "project_not_found", "The project does not exist.")
    return project


def owned_run(db: Session, session: AnonymousSession, run_id: str):
    """A design run owned (via its project) by the current session, else 404."""
    from saudi_plot_api.models import DesignRun, Project
    from sqlalchemy import select

    run = db.execute(
        select(DesignRun)
        .join(Project, Project.id == DesignRun.project_id)
        .where(DesignRun.id == run_id, Project.session_id == session.id)
    ).scalar_one_or_none()
    if run is None:
        raise ApiError(404, "design_run_not_found", "The design run does not exist.")
    return run
