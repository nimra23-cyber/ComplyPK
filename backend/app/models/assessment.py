"""SQLAlchemy ORM model for the single ``assessments`` table.

This is the only persisted entity in ComplyPK. A completed Assessment is stored
as one row: the answers, per-domain scores, gaps, and the (optional, cached)
remediation plan are heterogeneous nested data read as a unit, so they are kept
in JSON columns rather than normalized into extra tables (Req 2.4, 4.2).

The portable :class:`sqlalchemy.JSON` type maps to ``TEXT``(JSON) on SQLite and
``JSONB`` on PostgreSQL, so the same model works locally and in production
(Req 9.2, 9.3).

Layering: models have no upward dependency on repositories, services, or
routers (Req 12.2).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time (default for ``created_at``)."""
    return datetime.now(timezone.utc)


class Assessment(Base):
    """A completed readiness assessment and its computed results.

    Attributes:
        id: Unique assessment identifier (Req 2.5, 4.2).
        answers: Mapping of ``question_id -> "yes"|"partial"|"no"`` for all 20
            questions (Req 2.4).
        overall_score: Overall readiness score 0-100 (Req 2.1).
        domain_scores: Mapping of domain name -> score 0-100 (Req 2.2).
        gaps: List of gap objects, each with ``question_id``, ``domain``,
            ``answer``, ``severity``, ``iso_27001``, and ``nist_csf`` (Req 3).
        remediation_plan: Cached plan ``{"source": ..., "steps": [...]}`` or
            ``None`` until generated (Req 5, 6.4).
        created_at: Creation timestamp used for history ordering (Req 2.4, 4.1).
    """

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    answers: Mapped[dict] = mapped_column(JSON, nullable=False)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    domain_scores: Mapped[dict] = mapped_column(JSON, nullable=False)
    gaps: Mapped[list] = mapped_column(JSON, nullable=False)
    remediation_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Snapshot of the company profile at the time the assessment was created, so
    # each assessment retains the organization details that applied then. Nullable
    # for backward compatibility with assessments created before onboarding existed.
    company: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Owning tenant. Nullable for backward compatibility with legacy rows created
    # before multi-tenancy; legacy rows are claimed into a company during onboarding
    # and access control is enforced on this authorized relationship (not the snapshot).
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        index=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"Assessment(id={self.id!r}, overall_score={self.overall_score!r}, "
            f"created_at={self.created_at!r})"
        )
