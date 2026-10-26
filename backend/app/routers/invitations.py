"""Team invitation endpoints (email + shareable link).

Management (create/list/revoke/resend) is admin-only and scoped to the active
company via the existing authorization dependencies — a Company A admin can
never manage Company B's invitations, and client-supplied company ids/roles are
never trusted. Invitations always grant the ``member`` role.

Validation and acceptance require authentication (any user) but not admin.
Opening/validating a link never consumes it; acceptance is explicit and atomic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.config import load_settings
from app.db import get_db
from app.deps import CompanyContext, CurrentUser, ForbiddenError, get_current_user, require_admin
from app.errors import AppError, NotFoundError, ValidationError
from app.models.auth import INVITE_TYPE_EMAIL, INVITE_TYPE_LINK
from app.repositories.auth_repository import AuthRepository
from app.repositories.invitation_repository import InvitationRepository
from app.security import generate_token, hash_token
from app.services.email_service import (
    EmailDeliveryError,
    EmailNotConfigured,
    build_invitation_url,
    send_invitation_email,
)

router = APIRouter(prefix="/api", tags=["invitations"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _invite_response(inv) -> schemas.InvitationResponse:
    return schemas.InvitationResponse(
        id=inv.id,
        invite_type=inv.invite_type,
        email=inv.email,
        role=inv.role,
        status=inv.status,
        max_uses=inv.max_uses,
        use_count=inv.use_count,
        created_at=inv.created_at,
        expires_at=inv.expires_at,
    )


@router.post("/invitations/email", response_model=schemas.InvitationCreatedResponse, status_code=201)
def create_email_invitation(
    payload: schemas.EmailInviteInput,
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> schemas.InvitationCreatedResponse:
    """Create an email-bound invitation and attempt delivery (admin only).

    If email is not configured or delivery fails, the invitation is NOT created
    and a clear error is returned (never a false "sent").
    """
    settings = load_settings()
    if not settings.email_configured:
        raise AppError(503, "Email sending is not configured on the server.")

    auth = AuthRepository(db)
    company = auth.get_company(ctx.company_id)

    raw_token = generate_token()
    repo = InvitationRepository(db)
    inv = repo.create(
        company_id=ctx.company_id,
        inviter_user_id=ctx.user.id,
        token_hash=hash_token(raw_token),
        invite_type=INVITE_TYPE_EMAIL,
        email=str(payload.email),
        expires_at=_utcnow() + timedelta(hours=payload.expires_in_hours),
        max_uses=1,
    )

    try:
        send_invitation_email(settings, str(payload.email), company.name, raw_token)
    except (EmailNotConfigured, EmailDeliveryError) as exc:
        # Roll back the invitation so we never report a non-delivered invite as sent.
        repo.revoke(inv)
        raise AppError(502, str(exc))

    resp = _invite_response(inv)
    return schemas.InvitationCreatedResponse(**resp.model_dump(), share_url=None)


@router.post("/invitations/link", response_model=schemas.InvitationCreatedResponse, status_code=201)
def create_link_invitation(
    payload: schemas.LinkInviteInput,
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> schemas.InvitationCreatedResponse:
    """Create a shareable link invitation (admin only).

    Single-use by default. The raw token is returned once in ``share_url`` and
    never stored or logged.
    """
    settings = load_settings()
    raw_token = generate_token()
    repo = InvitationRepository(db)
    inv = repo.create(
        company_id=ctx.company_id,
        inviter_user_id=ctx.user.id,
        token_hash=hash_token(raw_token),
        invite_type=INVITE_TYPE_LINK,
        email=None,
        expires_at=_utcnow() + timedelta(hours=payload.expires_in_hours),
        max_uses=payload.max_uses,
    )
    share_url = build_invitation_url(settings.allowed_frontend_origin, raw_token)
    resp = _invite_response(inv)
    return schemas.InvitationCreatedResponse(**resp.model_dump(), share_url=share_url)


@router.get("/invitations", response_model=list[schemas.InvitationResponse])
def list_invitations(
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[schemas.InvitationResponse]:
    """List the active company's invitations (admin only)."""
    repo = InvitationRepository(db)
    out = []
    for inv in repo.list_for_company(ctx.company_id):
        repo.mark_expired_if_needed(inv)
        out.append(_invite_response(inv))
    return out


@router.post("/invitations/{invitation_id}/revoke", response_model=schemas.InvitationResponse)
def revoke_invitation(
    invitation_id: int,
    ctx: CompanyContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> schemas.InvitationResponse:
    """Revoke a pending invitation belonging to the active company (admin only)."""
    repo = InvitationRepository(db)
    inv = repo.get_for_company(invitation_id, ctx.company_id)
    if inv is None:
        # Company B cannot revoke Company A's invitation -> looks like not found.
        raise NotFoundError("Invitation not found.")
    repo.revoke(inv)
    return _invite_response(inv)


@router.get("/invitations/validate", response_model=schemas.InvitationValidateResponse)
def validate_invitation(
    token: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.InvitationValidateResponse:
    """Validate a token WITHOUT consuming it (safe for link previews).

    Requires authentication so that invitation existence is not probed anonymously.
    Returns a safe status; never reveals the token hash or inviter details.
    """
    if not token or len(token) < 10:
        return schemas.InvitationValidateResponse(valid=False, status="invalid")

    repo = InvitationRepository(db)
    inv = repo.get_by_token_hash(hash_token(token))
    if inv is None:
        return schemas.InvitationValidateResponse(valid=False, status="invalid")

    repo.mark_expired_if_needed(inv)
    if not repo.is_effectively_active(inv):
        return schemas.InvitationValidateResponse(valid=False, status=inv.status)

    company = AuthRepository(db).get_company(inv.company_id)
    return schemas.InvitationValidateResponse(
        valid=True,
        status=inv.status,
        company_name=company.name if company else None,
        invite_type=inv.invite_type,
        requires_email=inv.email,
    )


@router.post("/invitations/accept", response_model=schemas.InvitationAcceptResult)
def accept_invitation(
    payload: schemas.InvitationAcceptInput,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.InvitationAcceptResult:
    """Accept/redeem an invitation for the authenticated user.

    Acceptance is explicit and atomic: membership (member role only) is created
    exactly once, after all checks pass. Email invitations require a verified,
    matching email. The token is never logged.
    """
    token = payload.token

    repo = InvitationRepository(db)
    auth = AuthRepository(db)
    inv = repo.get_by_token_hash(hash_token(token))
    if inv is None:
        raise NotFoundError("This invitation is invalid.")

    repo.mark_expired_if_needed(inv)
    if not repo.is_effectively_active(inv):
        # Generic safe message; do not reveal company details for dead invites.
        raise ValidationError("This invitation is no longer valid.")

    db_user = auth.get_user(user.id)

    # Email invitations must match a verified email on the accepting account.
    if inv.invite_type == INVITE_TYPE_EMAIL:
        if inv.email is None or db_user.email.lower() != inv.email.lower():
            raise ForbiddenError("This invitation was issued to a different email address.")
        if not db_user.email_verified:
            raise ForbiddenError("You must verify your email address before accepting this invitation.")

    company = auth.get_company(inv.company_id)
    if company is None:
        raise NotFoundError("This invitation is invalid.")

    # Idempotent: if already a member, return a safe result without duplicating.
    existing = auth.get_membership(user.id, inv.company_id)
    if existing is not None:
        return schemas.InvitationAcceptResult(
            company_id=company.id, company_name=company.name, role=existing.role,
            already_member=True,
        )

    # Atomically consume one use; only then create the membership.
    if not repo.try_consume(inv.id, accepting_user_id=user.id):
        raise ValidationError("This invitation is no longer valid.")

    auth.add_membership(db_user, company, role="member")  # never admin
    return schemas.InvitationAcceptResult(
        company_id=company.id, company_name=company.name, role="member",
        already_member=False,
    )
