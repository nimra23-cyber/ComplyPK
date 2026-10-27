"""Application configuration.

Reads all configuration from environment variables at startup and fails fast on
invalid configuration. No URLs or secrets are hard-coded here; everything flows
through the Environment_Configuration (Req 9.1).

Fail-fast rules:
- ``ALLOWED_FRONTEND_ORIGIN`` must be set, otherwise startup aborts (Req 9.4).
- ``DATABASE_URL`` defaults to a local SQLite database when unset (Req 9.2).
- ``DATABASE_URL``, when set, must be a well-formed connection string; a malformed
  value aborts startup WITHOUT echoing its value (Req 9.5).

This module depends only on the Python standard library so it can be imported
cleanly before third-party dependencies are installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Local SQLite database file used when DATABASE_URL is not provided (Req 9.2).
# The scheme is a constant, not a secret or an externally supplied URL.
_DEFAULT_SQLITE_URL = "sqlite:///./complypk.db"

# backend/.env sits two levels up from this file (app/config.py -> app -> backend).
_BACKEND_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv_if_present() -> None:
    """Load variables from ``backend/.env`` into the process environment.

    Real OS environment variables take precedence (``override=False``), so this
    only fills in values that are not already set — safe for local development
    and inert in production where variables come from the host. Import-guarded so
    config still works if python-dotenv is unavailable. Never logs values.
    """
    try:
        from dotenv import load_dotenv
    except Exception:  # pragma: no cover - optional dependency
        return
    if _BACKEND_ENV_PATH.is_file():
        load_dotenv(dotenv_path=_BACKEND_ENV_PATH, override=False)


class ConfigError(RuntimeError):
    """Raised when the environment configuration is missing or invalid.

    The message never includes the value of DATABASE_URL or any other secret
    (Req 9.5, 9.8).
    """


@dataclass(frozen=True)
class Settings:
    """Resolved application settings.

    Attributes:
        allowed_frontend_origin: Exact origin permitted by CORS.
        database_url: Database connection string (SQLite default or provided).
        llm_api_key: Optional LLM credential; ``None`` triggers the fallback
            generator downstream.
    """

    allowed_frontend_origin: str
    database_url: str
    llm_api_key: str | None
    # Optional SMTP settings for sending email invitations. When any required
    # field is missing, email sending is considered unconfigured and email
    # invitations fail clearly (shareable links still work).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    # Optional Groq settings for AI-generated remediation. The key is read from
    # GROQ_API_KEY and is never exposed to the frontend. The model id is
    # configurable because Groq's catalog changes over time; verify availability
    # for your key (see README). When the key is absent, or the call fails/
    # rate-limits/times out/returns invalid output, the deterministic template
    # fallback is used.
    groq_api_key: str | None = None
    groq_model: str = "llama-3.1-8b-instant"

    @property
    def email_configured(self) -> bool:
        """True only when the minimum SMTP settings are present."""
        return bool(self.smtp_host and self.smtp_from)

    @property
    def groq_configured(self) -> bool:
        """True only when a Groq API key is present."""
        return bool(self.groq_api_key)


def _require_allowed_origin(raw: str | None) -> str:
    """Return the allowed frontend origin or raise if it is unset (Req 9.4)."""
    if raw is None or raw.strip() == "":
        raise ConfigError(
            "ALLOWED_FRONTEND_ORIGIN is not set. "
            "Set it to the exact origin of the frontend app (e.g. "
            "http://localhost:5173) before starting the service."
        )
    return raw.strip()


def _validate_database_url(raw: str | None) -> str:
    """Resolve and validate the database URL.

    Defaults to local SQLite when unset (Req 9.2). When provided, the value must
    be a well-formed connection string with a scheme and a location component.
    A malformed value raises ``ConfigError`` without echoing the value (Req 9.5).
    """
    if raw is None or raw.strip() == "":
        return _DEFAULT_SQLITE_URL

    candidate = raw.strip()

    try:
        parsed = urlparse(candidate)
    except ValueError as exc:  # pragma: no cover - urlparse rarely raises
        # Do not include the offending value in the message (Req 9.5).
        raise ConfigError(
            "DATABASE_URL is malformed and could not be parsed."
        ) from exc

    scheme = parsed.scheme
    # A usable connection string needs a driver scheme and a target location
    # (either a network netloc or a path, e.g. sqlite:///./file.db).
    has_location = bool(parsed.netloc) or bool(parsed.path)
    if not scheme or not has_location:
        # Never echo the DATABASE_URL value (Req 9.5).
        raise ConfigError(
            "DATABASE_URL is set but malformed. Expected a connection string "
            "such as 'sqlite:///./complypk.db' or "
            "'postgresql+psycopg://user:password@host:5432/dbname'."
        )

    return candidate


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    """Load and validate settings from the environment.

    Args:
        environ: Optional mapping to read from; defaults to ``os.environ``.
            Primarily useful for tests.

    Returns:
        A fully validated :class:`Settings` instance.

    Raises:
        ConfigError: If required configuration is missing or invalid.
    """
    if environ is None:
        # Fill missing values from backend/.env for local dev (OS env wins).
        _load_dotenv_if_present()
    env = os.environ if environ is None else environ

    allowed_frontend_origin = _require_allowed_origin(
        env.get("ALLOWED_FRONTEND_ORIGIN")
    )
    database_url = _validate_database_url(env.get("DATABASE_URL"))

    llm_api_key_raw = env.get("LLM_API_KEY")
    llm_api_key = (
        llm_api_key_raw.strip()
        if llm_api_key_raw and llm_api_key_raw.strip()
        else None
    )

    def _opt(name: str) -> str | None:
        v = env.get(name)
        return v.strip() if v and v.strip() else None

    smtp_port_raw = _opt("SMTP_PORT")
    try:
        smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
    except ValueError:
        smtp_port = 587

    return Settings(
        allowed_frontend_origin=allowed_frontend_origin,
        database_url=database_url,
        llm_api_key=llm_api_key,
        smtp_host=_opt("SMTP_HOST"),
        smtp_port=smtp_port,
        smtp_user=_opt("SMTP_USER"),
        smtp_password=_opt("SMTP_PASSWORD"),
        smtp_from=_opt("SMTP_FROM"),
        groq_api_key=_opt("GROQ_API_KEY"),
        groq_model=_opt("GROQ_MODEL") or "llama-3.1-8b-instant",
    )
