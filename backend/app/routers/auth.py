"""Authentication & company-membership router.

Endpoints:
- POST /api/auth/register   create a user
- POST /api/auth/login      start a session (sets HttpOnly cookie)
- POST /api/auth/logout     end the session
- GET  /api/auth/me         current user + memberships + CSRF token
- POST /api/companies       create a company (creator becomes admin)
- POST /api/companies/join  join an existing company

The session token is an opaque random value stored only as a hash server-side
and delivered in an HttpOnly, SameSite cookie (not readable by JS, so it cannot
be exfiltrated via XSS into localStorage). A CSRF token is returned for the
double-submit check on state-changing requests.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app import schemas
from app.config import load_settings
from app.db import get_db
from app.deps import (
    SESSION_COOKIE,
    CurrentUser,
    ForbiddenError,
    get_current_user,
)
from app.errors import AppError
from app.repositories.auth_repository import AuthRepository
from app.security import generate_token, hash_password, hash_token, verify_password

router = APIRouter(prefix="/api", tags=["auth"])

_SESSION_TTL_HOURS = 12


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(409, message)


def _is_secure_env() -> bool:
    """Set the cookie Secure flag when the frontend origin is HTTPS."""
    try:
        return load_settings().allowed_frontend_origin.lower().startswith("https://")
    except Exception:
        return False


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_is_secure_env(),
        max_age=_SESSION_TTL_HOURS * 3600,
        path="/",
    )


def _memberships_payload(repo: AuthRepository, user_id: int) -> list[schemas.MembershipInfo]:
    out: list[schemas.MembershipInfo] = []
    for m in repo.list_memberships(user_id):
        company = repo.get_company(m.company_id)
        out.append(
            schemas.MembershipInfo(
                company_id=m.company_id,
                company_name=company.name if company else "",
                role=m.role,
            )
        )
    return out


@router.post("/auth/register", status_code=201)
def register(payload: schemas.RegisterInput, db: Session = Depends(get_db)) -> dict:
    repo = AuthRepository(db)
    if repo.get_user_by_email(payload.email) is not None:
        # Generic conflict; do not reveal more than necessary.
        raise ConflictError("An account with that email already exists.")
    repo.create_user(email=str(payload.email), password_hash=hash_password(payload.password))
    return {"status": "registered"}


@router.post("/auth/login", response_model=schemas.MeResponse)
def login(
    payload: schemas.LoginInput, response: Response, db: Session = Depends(get_db)
) -> schemas.MeResponse:
    repo = AuthRepository(db)
    user = repo.get_user_by_email(payload.email)
    # Verify even when user is missing-ish to reduce enumeration/timing signals.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AppError(401, "Invalid email or password.")

    raw_token = generate_token()
    csrf = generate_token()
    repo.create_session(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token=csrf,
        ttl_hours=_SESSION_TTL_HOURS,
    )
    _set_session_cookie(response, raw_token)
    return schemas.MeResponse(
        user_id=user.id,
        email=user.email,
        memberships=_memberships_payload(repo, user.id),
        csrf_token=csrf,
    )


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    """End the current session and clear the cookie. Idempotent."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        AuthRepository(db).delete_session_by_token_hash(hash_token(token))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "logged_out"}


@router.get("/auth/me", response_model=schemas.MeResponse)
def me(
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> schemas.MeResponse:
    repo = AuthRepository(db)
    return schemas.MeResponse(
        user_id=user.id,
        email=user.email,
        memberships=_memberships_payload(repo, user.id),
        csrf_token=user.csrf_token,
    )


@router.post("/companies", response_model=schemas.MembershipInfo, status_code=201)
def create_company(
    payload: schemas.CompanyCreateInput,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.MembershipInfo:
    """Create a company; the authenticated user becomes its admin."""
    repo = AuthRepository(db)
    db_user = repo.get_user(user.id)
    company = repo.create_company_with_admin(payload.name.strip(), db_user)
    return schemas.MembershipInfo(company_id=company.id, company_name=company.name, role="admin")


@router.post("/companies/join", response_model=schemas.MembershipInfo)
def join_company(
    payload: schemas.CompanyJoinInput,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.MembershipInfo:
    """Join an existing company by id as a member."""
    repo = AuthRepository(db)
    company = repo.get_company(payload.company_id)
    if company is None:
        raise ForbiddenError("You do not have access to this company.")
    if repo.get_membership(user.id, company.id) is not None:
        return schemas.MembershipInfo(company_id=company.id, company_name=company.name, role=repo.get_membership(user.id, company.id).role)
    db_user = repo.get_user(user.id)
    repo.add_membership(db_user, company, role="member")
    return schemas.MembershipInfo(company_id=company.id, company_name=company.name, role="member")
