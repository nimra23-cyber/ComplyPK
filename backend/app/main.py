"""ComplyPK FastAPI application entry point.

Exposes the health probe plus the questionnaire and assessment APIs, configures
CORS from the Environment_Configuration, registers centralized error handlers
(Req 11.1, 11.2), and creates database tables at startup.

Startup fails fast if ``ALLOWED_FRONTEND_ORIGIN`` is unset because
:func:`app.config.load_settings` enforces it at import time (Req 9.1, 12.4).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_settings
from app.db import init_db
from app.errors import (
    AppError,
    app_error_handler,
    content_error_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.routers import (
    assessments,
    auth,
    company,
    demo,
    invitations,
    questionnaire,
)
from app.services.content_loader import ContentError

# Load and validate settings at startup. This raises ConfigError (aborting
# startup) when ALLOWED_FRONTEND_ORIGIN is unset or DATABASE_URL is malformed
# (Req 9.1, 9.4, 9.5).
settings = load_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create database tables if they do not yet exist, at startup."""
    init_db()
    yield


app = FastAPI(title="ComplyPK API", lifespan=lifespan)

# CORS permits only the exact configured frontend origin. Non-matching origins
# receive no CORS headers, so the browser blocks the response (Req 12.4, 12.5).
# The origin is read from config; it is never hard-coded here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Centralized error handlers render every error in the consistent
# ``{message, error_ref}`` shape without leaking stack traces or secrets
# (Req 11.1, 11.2).
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(ContentError, content_error_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Register API routers.
app.include_router(auth.router)
app.include_router(questionnaire.router)
app.include_router(assessments.router)
app.include_router(demo.router)
app.include_router(company.router)
app.include_router(invitations.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the deploy checkpoint (Req 12.7)."""
    return {"status": "ok"}
