"""Anonymous session endpoints.

The frozen frontend has no login page (FROZEN_FRONTEND_CONTRACT.md §4), so the
only credential is an anonymous session cookie: HttpOnly, SameSite, Secure
(with an explicit local-development override), carrying a random token whose
hash is stored server-side.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from saudi_plot_api.dependencies import (
    CurrentSessionDep,
    DbDep,
    SettingsDep,
    TrustedOriginDep,
)
from saudi_plot_api.schemas import SessionResponse
from saudi_plot_api.services.sessions import create_session

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


# The origin guard stops a cross-site form POST from replacing the victim's
# session cookie (login CSRF) -- the cookie is the only project credential.
@router.post("", response_model=SessionResponse, status_code=201, dependencies=[TrustedOriginDep])
def create(response: Response, settings: SettingsDep, db: DbDep) -> SessionResponse:
    issued = create_session(db, ttl_seconds=settings.session_ttl_seconds)
    response.set_cookie(
        key=settings.cookie_name,
        value=issued.token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    return SessionResponse.model_validate(issued.session)


@router.get("/current", response_model=SessionResponse)
def current(session: CurrentSessionDep) -> SessionResponse:
    return SessionResponse.model_validate(session)
