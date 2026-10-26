"""Repository for persisting and retrieving assessments (tenant-scoped).

Every method is scoped by ``company_id`` so that a company can only ever read or
modify its own assessments. Ownership is enforced here in the data layer, in
addition to the authorization dependency at the route layer (defense in depth).

Depends only on the ORM model and a SQLAlchemy :class:`Session` (Req 12.2).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment import Assessment


class AssessmentRepository:
    """Data-access layer for :class:`Assessment` rows, scoped by company."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def save(
        self,
        company_id: int,
        answers: dict,
        overall_score: int,
        domain_scores: dict,
        gaps: list,
        remediation_plan: dict | None = None,
        company: dict | None = None,
    ) -> Assessment:
        """Persist a new assessment owned by ``company_id`` (Req 2.4, 2.5)."""
        assessment = Assessment(
            company_id=company_id,
            answers=answers,
            overall_score=overall_score,
            domain_scores=domain_scores,
            gaps=gaps,
            remediation_plan=remediation_plan,
            company=company,
        )
        self._db.add(assessment)
        self._db.commit()
        self._db.refresh(assessment)
        return assessment

    def list(self, company_id: int) -> list[Assessment]:
        """Return this company's assessments, most recent first (Req 4.1)."""
        stmt = (
            select(Assessment)
            .where(Assessment.company_id == company_id)
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        )
        return list(self._db.scalars(stmt).all())

    def get(self, assessment_id: int, company_id: int) -> Assessment | None:
        """Return the assessment only if it belongs to ``company_id``.

        Scoping the query by company means a guessed/forged id for another
        company's assessment returns ``None`` (handled as 404 by the route),
        never another tenant's data.
        """
        stmt = select(Assessment).where(
            Assessment.id == assessment_id, Assessment.company_id == company_id
        )
        return self._db.scalars(stmt).first()

    def update_remediation(
        self, assessment_id: int, company_id: int, plan: dict
    ) -> Assessment | None:
        """Cache a remediation plan, only for this company's assessment."""
        assessment = self.get(assessment_id, company_id)
        if assessment is None:
            return None
        assessment.remediation_plan = plan
        self._db.commit()
        self._db.refresh(assessment)
        return assessment

    # --- Legacy claim (onboarding) ------------------------------------------

    def list_unowned(self) -> list[Assessment]:
        """Return assessments with no owning company (legacy rows)."""
        stmt = select(Assessment).where(Assessment.company_id.is_(None))
        return list(self._db.scalars(stmt).all())

    def claim_unowned(self, company_id: int) -> int:
        """Assign all unowned assessments to ``company_id``. Returns the count."""
        unowned = self.list_unowned()
        for a in unowned:
            a.company_id = company_id
        self._db.commit()
        return len(unowned)
