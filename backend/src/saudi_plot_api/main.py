"""FastAPI application factory for the web adapter.

Run locally (after ``pip install -e ".[dev,web]"`` and ``alembic upgrade head``,
or ``python -m saudi_plot_api.migrate`` where no alembic.ini exists)::

    uvicorn --factory saudi_plot_api.main:create_app --reload

The factory owns the engine/session-factory on ``app.state`` so tests can build
fully isolated apps with their own settings and database.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from saudi_plot_api.config import Settings
from saudi_plot_api.database import create_database_engine, create_session_factory
from saudi_plot_api.errors import error_response, logger, register_exception_handlers
from saudi_plot_api.routes import (
    briefs,
    design_runs,
    documents,
    health,
    plots,
    pricing,
    projects,
    sessions,
    share,
)
from saudi_plot_api.services.runner import create_executor


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    app = FastAPI(
        title="Saudi Plot Design web adapter",
        version="0.1.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = create_database_engine(settings.database_url)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.run_executor = create_executor()

    # Innermost of the three middleware layers: converts unexpected exceptions
    # into the envelope INSIDE the stack, so the 500 still flows out through
    # CORSMiddleware (the frontend can read it) and the request-id middleware.
    # Starlette's own ServerErrorMiddleware sits outside everything and would
    # otherwise bypass both (the @app.exception_handler(Exception) in errors.py
    # stays registered as a last-resort fallback).
    @app.middleware("http")
    async def unexpected_error_middleware(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.exception(
                "unhandled error (request_id=%s)", getattr(request.state, "request_id", None)
            )
            return error_response(request, 500, "internal_error", "An internal error occurred.")

    if settings.cors_origins:
        # Cookie auth means credentialed CORS; Settings already refuses "*".
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH"],
            allow_headers=["Content-Type"],
        )

    # Added after CORSMiddleware so it is the OUTERMOST layer: every response,
    # including CORS preflight rejections, gets a request id -- and rejected
    # preflights are rewritten into the stable error envelope.
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        response = await call_next(request)
        if (
            request.method == "OPTIONS"
            and "access-control-request-method" in request.headers
            and response.status_code == 400
            and response.headers.get("content-type", "").startswith("text/plain")
        ):
            response = error_response(
                request, 400, "cors_rejected", "Cross-origin request not allowed."
            )
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(projects.router)
    app.include_router(documents.router)
    app.include_router(plots.router)
    app.include_router(briefs.router)
    app.include_router(design_runs.router)
    app.include_router(share.router)
    app.include_router(pricing.router)

    return app
