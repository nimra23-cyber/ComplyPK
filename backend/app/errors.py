"""Centralized error handling (Req 11.1, 11.2).

Defines a small application-error type and the FastAPI exception handlers that
render every error as a consistent JSON body ``{"message": ..., "error_ref":
...}``. The ``error_ref`` is a per-error UUID for log correlation; client
messages are generic and never include stack traces, file paths, or secret
values (Req 9.8, 11.1).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import ErrorResponse
from app.services.content_loader import ContentError

logger = logging.getLogger("complypk")


class AppError(Exception):
    """An application error with an associated HTTP status code.

    The ``message`` is safe to return to clients; it must never contain secrets
    or internal details.
    """

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class NotFoundError(AppError):
    """Requested resource does not exist (HTTP 404)."""

    def __init__(self, message: str = "The requested resource was not found.") -> None:
        super().__init__(404, message)


class ValidationError(AppError):
    """Request failed domain validation (HTTP 422)."""

    def __init__(self, message: str = "The request was invalid.") -> None:
        super().__init__(422, message)


def _error_body(message: str) -> dict[str, str]:
    """Build a consistent error body with a fresh correlation id (Req 11.2)."""
    return ErrorResponse(message=message, error_ref=str(uuid.uuid4())).model_dump()


def _json_error(status_code: int, message: str, error_ref: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"message": message, "error_ref": error_ref},
    )


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    """Render :class:`AppError` subclasses with their status and safe message."""
    error_ref = str(uuid.uuid4())
    logger.info("app_error ref=%s status=%s", error_ref, exc.status_code)
    return _json_error(exc.status_code, exc.message, error_ref)


async def content_error_handler(_: Request, exc: ContentError) -> JSONResponse:
    """Map content-file problems to HTTP 500 without leaking details (Req 1.4, 3.6)."""
    error_ref = str(uuid.uuid4())
    # Log the safe message plus the ref; never log secrets or stack traces here.
    logger.error("content_error ref=%s: %s", error_ref, str(exc))
    return _json_error(500, str(exc), error_ref)


async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render FastAPI/Pydantic validation errors in the consistent shape (Req 10.2)."""
    error_ref = str(uuid.uuid4())
    # Summarize offending fields without echoing full payloads.
    fields = ", ".join(
        ".".join(str(loc) for loc in err.get("loc", []) if loc != "body")
        for err in exc.errors()
    )
    message = "Request validation failed."
    if fields:
        message = f"Request validation failed for: {fields}."
    logger.info("validation_error ref=%s fields=%s", error_ref, fields)
    return _json_error(422, message, error_ref)


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Catch-all: generic HTTP 500, no stack trace or secret leakage (Req 11.1)."""
    error_ref = str(uuid.uuid4())
    # Full details go to server logs only, keyed by the correlation id.
    logger.exception("unhandled_error ref=%s", error_ref)
    return _json_error(
        500,
        "An unexpected error occurred. Please try again later.",
        error_ref,
    )
