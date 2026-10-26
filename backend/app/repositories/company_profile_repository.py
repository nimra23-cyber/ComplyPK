"""Repository for the company profile (tenant-scoped).

Each company has its own profile, scoped by ``company_id``. Depends only on the
ORM model and a SQLAlchemy :class:`Session` (Req 12.2).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company_profile import CompanyProfile


class CompanyProfileRepository:
    """Data-access layer for :class:`CompanyProfile`, scoped by company."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_for_company(self, company_id: int) -> CompanyProfile | None:
        """Return this company's most recent profile, or ``None``."""
        stmt = (
            select(CompanyProfile)
            .where(CompanyProfile.company_id == company_id)
            .order_by(CompanyProfile.updated_at.desc(), CompanyProfile.id.desc())
        )
        return self._db.scalars(stmt).first()

    def create(self, company_id: int, **fields) -> CompanyProfile:
        profile = CompanyProfile(company_id=company_id, **fields)
        self._db.add(profile)
        self._db.commit()
        self._db.refresh(profile)
        return profile

    def update_for_company(self, company_id: int, **fields) -> CompanyProfile | None:
        profile = self.get_for_company(company_id)
        if profile is None:
            return None
        for key, value in fields.items():
            setattr(profile, key, value)
        self._db.commit()
        self._db.refresh(profile)
        return profile

    # --- Legacy claim (onboarding) ------------------------------------------

    def count_unowned(self) -> int:
        """Return the number of profiles with no owning company."""
        stmt = select(CompanyProfile).where(CompanyProfile.company_id.is_(None))
        return len(list(self._db.scalars(stmt).all()))

    def claim_unowned(self, company_id: int) -> int:
        """Assign unowned profiles to ``company_id``. Returns the count."""
        stmt = select(CompanyProfile).where(CompanyProfile.company_id.is_(None))
        unowned = list(self._db.scalars(stmt).all())
        for p in unowned:
            p.company_id = company_id
        self._db.commit()
        return len(unowned)
