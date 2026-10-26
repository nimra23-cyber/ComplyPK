"""SQLAlchemy ORM model for the ``company_profiles`` table.

Stores the organization profile used for onboarding. ComplyPK is single-user /
single-tenant (no authentication), so the application treats the most recently
updated profile as the current company profile. This table is additive: it is
created by ``create_all`` and does not alter or remove existing data.

Layering: models have no upward dependency on repositories, services, or
routers (Req 12.2).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CompanyProfile(Base):
    """An organization profile captured during onboarding.

    Attributes:
        id: Unique profile identifier.
        name: Company name (required).
        industry: Optional industry/sector.
        size: Optional company size descriptor.
        country: Optional country.
        contact_email: Optional contact email.
        created_at / updated_at: Timestamps; ``updated_at`` determines which
            profile is considered current.
    """

    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Owning tenant (nullable for legacy rows; set during onboarding/claim).
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size: Mapped[str | None] = mapped_column(String(80), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"CompanyProfile(id={self.id!r}, name={self.name!r})"
