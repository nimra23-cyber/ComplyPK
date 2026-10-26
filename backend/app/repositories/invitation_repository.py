"""Repository for team invitations (tenant-scoped, atomic redemption).

Encapsulates all DB access for ``invitations``. Lookups and management are
scoped by ``company_id``; redemption is performed with a guarded UPDATE so a
token cannot be redeemed beyond its ``max_uses`` even under concurrency.

Depends only on ORM models and a SQLAlchemy :class:`Session` (Req 12.2).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.auth import (
    INVITE_ACCEPTED,
    INVITE_EXPIRED,
    INVITE_PENDING,
    INVITE_REVOKED,
    Invitation,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """Normalize a possibly-naive (SQLite) datetime to aware UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class InvitationRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        company_id: int,
        inviter_user_id: int,
        token_hash: str,
        invite_type: str,
        expires_at: datetime,
        email: str | None = None,
        max_uses: int = 1,
    ) -> Invitation:
        inv = Invitation(
            company_id=company_id,
            inviter_user_id=inviter_user_id,
            token_hash=token_hash,
            invite_type=invite_type,
            role="member",  # never admin
            status=INVITE_PENDING,
            email=email.lower() if email else None,
            max_uses=max_uses,
            use_count=0,
            expires_at=expires_at,
        )
        self._db.add(inv)
        self._db.commit()
        self._db.refresh(inv)
        return inv

    def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        stmt = select(Invitation).where(Invitation.token_hash == token_hash)
        return self._db.scalars(stmt).first()

    def get_for_company(self, invitation_id: int, company_id: int) -> Invitation | None:
        stmt = select(Invitation).where(
            Invitation.id == invitation_id, Invitation.company_id == company_id
        )
        return self._db.scalars(stmt).first()

    def list_for_company(self, company_id: int) -> list[Invitation]:
        stmt = (
            select(Invitation)
            .where(Invitation.company_id == company_id)
            .order_by(Invitation.created_at.desc(), Invitation.id.desc())
        )
        return list(self._db.scalars(stmt).all())

    def is_effectively_active(self, inv: Invitation) -> bool:
        """True if the invitation is pending, unexpired, and has uses left."""
        if inv.status != INVITE_PENDING:
            return False
        if _aware(inv.expires_at) <= _utcnow():
            return False
        if inv.use_count >= inv.max_uses:
            return False
        return True

    def mark_expired_if_needed(self, inv: Invitation) -> Invitation:
        """Persist an expired status for a pending-but-past-expiry invitation."""
        if inv.status == INVITE_PENDING and _aware(inv.expires_at) <= _utcnow():
            inv.status = INVITE_EXPIRED
            self._db.commit()
            self._db.refresh(inv)
        return inv

    def revoke(self, inv: Invitation) -> Invitation:
        inv.status = INVITE_REVOKED
        self._db.commit()
        self._db.refresh(inv)
        return inv

    def try_consume(self, invitation_id: int, accepting_user_id: int) -> bool:
        """Atomically consume one use of a pending, unexpired invitation.

        Uses a conditional UPDATE (WHERE status=pending AND use_count<max_uses
        AND not expired) so two concurrent accepts cannot both succeed. Returns
        True if this call consumed a use; False otherwise (already used/expired/
        revoked). The caller creates the membership only when this returns True.
        """
        now = _utcnow()
        stmt = (
            update(Invitation)
            .where(
                Invitation.id == invitation_id,
                Invitation.status == INVITE_PENDING,
                Invitation.use_count < Invitation.max_uses,
                Invitation.expires_at > now,
            )
            .values(use_count=Invitation.use_count + 1)
            # Evaluate the WHERE in SQL, not in Python, to avoid comparing a
            # naive (SQLite) datetime against an aware one in the ORM evaluator.
            .execution_options(synchronize_session=False)
        )
        result = self._db.execute(stmt)
        # The session may hold a stale copy; expire it so the subsequent get()
        # reflects the committed use_count.
        self._db.expire_all()
        if result.rowcount != 1:
            self._db.rollback()
            return False

        # Finalize: if fully consumed, flip to accepted and record acceptance.
        inv = self._db.get(Invitation, invitation_id)
        if inv.use_count >= inv.max_uses:
            inv.status = INVITE_ACCEPTED
        if inv.accepted_user_id is None:
            inv.accepted_user_id = accepting_user_id
            inv.accepted_at = now
        self._db.commit()
        return True
