"""Repository for users, companies, memberships, and sessions.

Encapsulates all DB access for authentication and tenancy. Depends only on ORM
models and a SQLAlchemy :class:`Session` (Req 12.2).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import Company, Membership, User, UserSession


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # --- Users ---------------------------------------------------------------

    def get_user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return self._db.scalars(stmt).first()

    def get_user(self, user_id: int) -> User | None:
        return self._db.get(User, user_id)

    def create_user(self, email: str, password_hash: str) -> User:
        user = User(email=email.lower(), password_hash=password_hash)
        self._db.add(user)
        self._db.commit()
        self._db.refresh(user)
        return user

    # --- Companies & memberships --------------------------------------------

    def get_company(self, company_id: int) -> Company | None:
        return self._db.get(Company, company_id)

    def create_company_with_admin(self, name: str, user: User) -> Company:
        company = Company(name=name)
        self._db.add(company)
        self._db.flush()  # assign company.id
        membership = Membership(user_id=user.id, company_id=company.id, role="admin")
        self._db.add(membership)
        self._db.commit()
        self._db.refresh(company)
        return company

    def add_membership(self, user: User, company: Company, role: str = "member") -> Membership:
        membership = Membership(user_id=user.id, company_id=company.id, role=role)
        self._db.add(membership)
        self._db.commit()
        self._db.refresh(membership)
        return membership

    def get_membership(self, user_id: int, company_id: int) -> Membership | None:
        stmt = select(Membership).where(
            Membership.user_id == user_id, Membership.company_id == company_id
        )
        return self._db.scalars(stmt).first()

    def list_memberships(self, user_id: int) -> list[Membership]:
        stmt = select(Membership).where(Membership.user_id == user_id)
        return list(self._db.scalars(stmt).all())

    # --- Sessions ------------------------------------------------------------

    def create_session(
        self, user_id: int, token_hash: str, csrf_token: str, ttl_hours: int = 12
    ) -> UserSession:
        now = _utcnow()
        session = UserSession(
            token_hash=token_hash,
            user_id=user_id,
            csrf_token=csrf_token,
            created_at=now,
            expires_at=now + timedelta(hours=ttl_hours),
        )
        self._db.add(session)
        self._db.commit()
        self._db.refresh(session)
        return session

    def get_session_by_token_hash(self, token_hash: str) -> UserSession | None:
        stmt = select(UserSession).where(UserSession.token_hash == token_hash)
        session = self._db.scalars(stmt).first()
        if session is None:
            return None
        # SQLite returns naive datetimes; normalize to aware UTC for comparison.
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= _utcnow():
            # Expired: delete and treat as absent.
            self._db.delete(session)
            self._db.commit()
            return None
        return session

    def delete_session_by_token_hash(self, token_hash: str) -> None:
        stmt = select(UserSession).where(UserSession.token_hash == token_hash)
        session = self._db.scalars(stmt).first()
        if session is not None:
            self._db.delete(session)
            self._db.commit()
