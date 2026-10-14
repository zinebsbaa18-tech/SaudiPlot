"""Liveness and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from saudi_plot_api.errors import ApiError

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/ready")
def ready(request: Request) -> dict[str, str]:
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise ApiError(503, "database_unavailable", "The database is not reachable.") from exc
    return {"status": "ready"}
