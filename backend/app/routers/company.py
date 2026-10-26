"""Company profile router (tenant-scoped) + legacy-data onboarding.

All endpoints require authentication and an authorized company context; the
profile is scoped to the active company. The onboarding claim endpoint lets a
Company Admin assign pre-existing (unowned) legacy records to their company —
an explicit, confirmed action, never a silent assignment (Req 5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.deps import CompanyContext, require_admin, require_company
from app.errors import NotFoundError
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.company_profile_repository import CompanyProfileRepository

router = APIRouter(prefix="/api", tags=["company"])


def _to_response(profile) -> schemas.CompanyProfileResponse:
    return schemas.CompanyProfileResponse(
        id=profile.id,
        name=profile.name,
        industry=profile.industry,
        size=profile.size,
        country=profile.country,
        contact_email=profile.contact_email,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get("/company", response_model=schemas.CompanyProfileResponse)
def get_company(
    ctx: CompanyContext = Depends(require_company), db: Session = Depends(get_db)
) -> schemas.CompanyProfileResponse:
    """Return the active company's profile, or 404 if none exists yet."""
    profile = CompanyProfileRepository(db).get_for_company(ctx.company_id)
    if profile is None:
        raise NotFoundError("No company profile has been created yet.")
    return _to_response(profile)


@router.post("/company", response_model=schemas.CompanyProfileResponse, status_code=201)
def create_company_profile(
    payload: schemas.CompanyProfileInput,
    ctx: CompanyContext = Depends(require_company),
    db: Session = Depends(get_db),
) -> schemas.CompanyProfileResponse:
    """Create the active company's profile."""
    repo = CompanyProfileRepository(db)
    # If one already exists for this company, update it instead of duplicating.
    existing = repo.get_for_company(ctx.company_id)
    fields = {
        "name": payload.name.strip(),
        "industry": payload.industry,
        "size": payload.size,
        "country": payload.country,
        "contact_email": str(payload.contact_email) if payload.contact_email else None,
    }
    if existing is not None:
        profile = repo.update_for_company(ctx.company_id, **fields)
    else:
        profile = repo.create(ctx.company_id, **fields)
    return _to_response(profile)


@router.put("/company", response_model=schemas.CompanyProfileResponse)
def update_company_profile(
    payload: schemas.CompanyProfileInput,
    ctx: CompanyContext = Depends(require_company),
    db: Session = Depends(get_db),
) -> schemas.CompanyProfileResponse:
    """Update the active company's profile, creating it if absent."""
    repo = CompanyProfileRepository(db)
    fields = {
        "name": payload.name.strip(),
        "industry": payload.industry,
        "size": payload.size,
        "country": payload.country,
        "contact_email": str(payload.contact_email) if payload.contact_email else None,
    }
    profile = repo.update_for_company(ctx.company_id, **fields)
    if profile is None:
        profile = repo.create(ctx.company_id, **fields)
    return _to_response(profile)


@router.get("/company/legacy", response_model=schemas.LegacyDataInfo)
def legacy_summary(
    ctx: CompanyContext = Depends(require_company), db: Session = Depends(get_db)
) -> schemas.LegacyDataInfo:
    """Report how many pre-existing, unowned records are available to claim."""
    unowned_assessments = len(AssessmentRepository(db).list_unowned())
    unowned_profiles = CompanyProfileRepository(db).count_unowned()
    return schemas.LegacyDataInfo(
        unowned_assessments=unowned_assessments,
        unowned_profiles=unowned_profiles,
    )


@router.post("/company/legacy/claim", response_model=schemas.LegacyClaimResult)
def claim_legacy(
    ctx: CompanyContext = Depends(require_admin), db: Session = Depends(get_db)
) -> schemas.LegacyClaimResult:
    """Claim all unowned legacy records into the active company (admin only).

    This is the explicit, confirmed onboarding step that assigns historical
    single-company data to a real tenant. It never runs automatically.
    """
    claimed_assessments = AssessmentRepository(db).claim_unowned(ctx.company_id)
    claimed_profiles = CompanyProfileRepository(db).claim_unowned(ctx.company_id)
    return schemas.LegacyClaimResult(
        claimed_assessments=claimed_assessments,
        claimed_profiles=claimed_profiles,
    )
