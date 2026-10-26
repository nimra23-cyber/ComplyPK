"""Authentication & authorization dependencies (tenant isolation core).

Access control is derived from the authenticated session and the user's
memberships — never from a client-supplied company name or an untrusted body/
query parameter. The active company is taken from the ``X-Company-Id`` request
header and validated against the user's memberships; a mismatch yields 403.

This is the single choke point every company-scoped endpoint depends on.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.repositories.auth_repository import AuthRepository
from app.security import constant_time_equals, hash_token

SESSION_COOKIE = "complypk_session"
CSRF_HEADER = "X-CSRF-Token"
COMPANY_HEADER = "X-Company-Id"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class AuthError(AppError):
    """Not authenticated (HTTP 401)."""

    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(401, message)


class ForbiddenError(AppError):
    """Authenticated but not authorized (HTTP 403)."""

    def __init__(self, message: str = "You do not have access to this resource.") -> None:
        super().__init__(403, message)


@dataclass
class CurrentUser:
    id: int
    email: str
    csrf_token: str


@dataclass
class CompanyContext:
    """The authorized scope for a request: the user plus their active company."""

    user: CurrentUser
    company_id: int
    role: str


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    """Resolve the authenticated user from the session cookie, or 401.

    Also enforces CSRF for unsafe methods using a double-submit token: the
    ``X-CSRF-Token`` header must match the session's stored CSRF token.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthError()

    repo = AuthRepository(db)
    session = repo.get_session_by_token_hash(hash_token(token))
    if session is None:
        raise AuthError("Your session has expired. Please sign in again.")

    # CSRF protection for state-changing requests (cookie-based auth).
    if request.method.upper() not in _SAFE_METHODS:
        header_csrf = request.headers.get(CSRF_HEADER, "")
        if not header_csrf or not constant_time_equals(header_csrf, session.csrf_token):
            raise ForbiddenError("Invalid or missing CSRF token.")

    user = repo.get_user(session.user_id)
    if user is None:
        raise AuthError()
    return CurrentUser(id=user.id, email=user.email, csrf_token=session.csrf_token)


def require_company(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CompanyContext:
    """Derive and authorize the active company from the session + membership.

    The company id comes from the ``X-Company-Id`` header and MUST correspond to
    a membership of the authenticated user. If the user belongs to exactly one
    company and no header is supplied, that company is used. A header for a
    company the user is not a member of yields 403 — this is what prevents
    cross-tenant access via a guessed/modified id.
    """
    repo = AuthRepository(db)
    memberships = repo.list_memberships(user.id)
    if not memberships:
        raise ForbiddenError("You are not a member of any company yet.")

    header_value = request.headers.get(COMPANY_HEADER)
    if header_value is None or header_value.strip() == "":
        if len(memberships) == 1:
            m = memberships[0]
            return CompanyContext(user=user, company_id=m.company_id, role=m.role)
        raise ForbiddenError(
            "Multiple companies available; specify the active company."
        )

    try:
        company_id = int(header_value)
    except (TypeError, ValueError):
        raise ForbiddenError("Invalid company identifier.")

    match = next((m for m in memberships if m.company_id == company_id), None)
    if match is None:
        # Do not reveal whether the company exists — just deny.
        raise ForbiddenError("You do not have access to this company.")
    return CompanyContext(user=user, company_id=match.company_id, role=match.role)


def require_admin(ctx: CompanyContext = Depends(require_company)) -> CompanyContext:
    """Require the Company Admin role for the active company."""
    if ctx.role != "admin":
        raise ForbiddenError("This action requires the Company Admin role.")
    return ctx
