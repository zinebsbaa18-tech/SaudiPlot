"""Application error type and exception handlers producing the stable envelope.

Every error response has the same shape (schemas.ErrorEnvelope) and never
carries stack traces, SQL, file paths, or secrets.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("saudi_plot_api")


class ApiError(Exception):
    """Machine-readable application error carried to the envelope unchanged."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "details": details or {}},
            "request_id": getattr(request.state, "request_id", None),
        },
    )


_HTTP_STATUS_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(request, exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Only field locations and messages -- never the submitted input values,
        # which pydantic includes by default and may contain sensitive data.
        fields = [
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "message": err.get("msg", "invalid"),
            }
            for err in exc.errors()
        ]
        return error_response(
            request,
            422,
            "invalid_payload",
            "The request payload is invalid.",
            {"fields": fields},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Full detail goes to the server log only; the client gets a safe shell.
        logger.exception(
            "unhandled error (request_id=%s)", getattr(request.state, "request_id", None)
        )
        return error_response(request, 500, "internal_error", "An internal error occurred.")
