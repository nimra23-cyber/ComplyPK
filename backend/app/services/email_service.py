"""Email delivery for invitations (SMTP, configurable via environment).

Credentials come only from environment variables (never hardcoded). When SMTP
is not configured, :func:`send_invitation_email` raises :class:`EmailNotConfigured`
so the caller can report the failure clearly instead of claiming success. The
invitation URL is built from the validated configured frontend origin — never
from a client-supplied Host header. Raw tokens are never logged.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import Settings

logger = logging.getLogger("complypk")

_SMTP_TIMEOUT_SECONDS = 15


class EmailNotConfigured(RuntimeError):
    """Raised when SMTP settings are incomplete and email cannot be sent."""


class EmailDeliveryError(RuntimeError):
    """Raised when the SMTP provider fails or times out."""


def build_invitation_url(frontend_origin: str, raw_token: str) -> str:
    """Build the acceptance URL from the configured frontend origin."""
    base = frontend_origin.rstrip("/")
    return f"{base}/index.html#invite={raw_token}"


def build_verification_url(frontend_origin: str, raw_token: str) -> str:
    """Build the email-verification URL from the configured frontend origin."""
    base = frontend_origin.rstrip("/")
    return f"{base}/index.html#verify={raw_token}"


def send_verification_email(settings: Settings, recipient: str, raw_token: str) -> None:
    """Send an email-verification message, or raise on config/delivery failure.

    The raw token is delivered ONLY here (via email); it is never returned by
    the API, so a user cannot self-verify without inbox access. Never logs the
    raw token or SMTP password.
    """
    if not settings.email_configured:
        raise EmailNotConfigured(
            "Email sending is not configured. Set SMTP_HOST and SMTP_FROM "
            "(and credentials) to enable email verification."
        )
    url = build_verification_url(settings.allowed_frontend_origin, raw_token)
    msg = EmailMessage()
    msg["Subject"] = "Verify your ComplyPK email address"
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg.set_content(
        "Confirm your email address for ComplyPK by opening:\n"
        f"{url}\n\nThis link will expire. If you did not request this, ignore it."
    )
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT_SECONDS) as server:
            server.starttls(context=context)
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        logger.error("verification_email_delivery_failed: %s", type(exc).__name__)
        raise EmailDeliveryError("The verification email could not be delivered.") from exc


def send_invitation_email(
    settings: Settings, recipient: str, company_name: str, raw_token: str
) -> None:
    """Send an invitation email, or raise on config/delivery failure.

    Never logs the raw token or SMTP password.
    """
    if not settings.email_configured:
        raise EmailNotConfigured(
            "Email sending is not configured. Set SMTP_HOST and SMTP_FROM "
            "(and credentials) to enable email invitations."
        )

    url = build_invitation_url(settings.allowed_frontend_origin, raw_token)
    msg = EmailMessage()
    msg["Subject"] = f"You're invited to join {company_name} on ComplyPK"
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg.set_content(
        f"You have been invited to join {company_name} on ComplyPK as a team member.\n\n"
        f"To accept, sign in or create an account with this email address, then open:\n{url}\n\n"
        "This invitation will expire. If you did not expect this, you can ignore it."
    )

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT_SECONDS) as server:
            server.starttls(context=context)
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except Exception as exc:  # noqa: BLE001 - surface a safe, generic error
        # Log the failure type only (no token, no password, no recipient body).
        logger.error("invitation_email_delivery_failed: %s", type(exc).__name__)
        raise EmailDeliveryError("The invitation email could not be delivered.") from exc
