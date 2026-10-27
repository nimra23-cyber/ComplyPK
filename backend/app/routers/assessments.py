"""Assessments router: submit, list history, fetch, remediate, export report.

Every endpoint requires authentication and an authorized company context
(:func:`require_company`), and all persistence is scoped by that company id, so
a company can only ever access its own assessments (Req 2, 3, 4, 5, 6). A
guessed/forged assessment id belonging to another company returns 404.

Scoring, gap-mapping, remediation, and report logic are unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.deps import CompanyContext, require_company
from app.errors import NotFoundError, ValidationError
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.company_profile_repository import CompanyProfileRepository
from app.services.content_loader import load_control_mapping, load_questions
from app.services.gap_mapping_service import build_gaps
from app.services.remediation_service import generate_remediation_plan
from app.services.report_service import render_markdown_report
from app.services.scoring_service import compute_domain_scores, compute_overall_score

router = APIRouter(prefix="/api", tags=["assessments"])


def _validate_answers(answers: dict[str, str], question_ids: set[str]) -> None:
    submitted = set(answers.keys())
    missing = question_ids - submitted
    unknown = submitted - question_ids
    if missing or unknown:
        parts: list[str] = []
        if missing:
            parts.append("missing question ids: " + ", ".join(sorted(missing)))
        if unknown:
            parts.append("unknown question ids: " + ", ".join(sorted(unknown)))
        raise ValidationError("Invalid submission — " + "; ".join(parts) + ".")


def _to_response(assessment) -> schemas.AssessmentResponse:
    return schemas.AssessmentResponse(
        id=assessment.id,
        created_at=assessment.created_at,
        overall_score=assessment.overall_score,
        domain_scores=assessment.domain_scores,
        gaps=[schemas.Gap(**gap) for gap in assessment.gaps],
        company=assessment.company,
    )


@router.post("/assessments", response_model=schemas.AssessmentResponse, status_code=201)
def submit_assessment(
    submission: schemas.AnswerSubmission,
    ctx: CompanyContext = Depends(require_company),
    db: Session = Depends(get_db),
) -> schemas.AssessmentResponse:
    """Score, map gaps, persist (owned by the active company), and return."""
    questions = load_questions()
    control_mapping = load_control_mapping()
    _validate_answers(submission.answers, {q.id for q in questions})

    overall = compute_overall_score(submission.answers, questions)
    domain_scores = compute_domain_scores(submission.answers, questions)
    gaps = build_gaps(submission.answers, questions, control_mapping)

    # Snapshot this company's current profile (if any) for historical accuracy.
    profile = CompanyProfileRepository(db).get_for_company(ctx.company_id)
    company_snapshot = None
    if profile is not None:
        company_snapshot = {
            "name": profile.name,
            "industry": profile.industry,
            "size": profile.size,
            "country": profile.country,
        }

    repo = AssessmentRepository(db)
    stored = repo.save(
        company_id=ctx.company_id,
        answers=submission.answers,
        overall_score=overall,
        domain_scores=domain_scores,
        gaps=[gap.model_dump() for gap in gaps],
        company=company_snapshot,
    )
    return _to_response(stored)


@router.get("/assessments", response_model=list[schemas.AssessmentSummary])
def list_assessments(
    ctx: CompanyContext = Depends(require_company),
    db: Session = Depends(get_db),
) -> list[schemas.AssessmentSummary]:
    """Return the active company's assessment history (Req 4.1, 4.4, 4.5)."""
    repo = AssessmentRepository(db)
    return [
        schemas.AssessmentSummary(id=a.id, created_at=a.created_at, overall_score=a.overall_score)
        for a in repo.list(ctx.company_id)
    ]


@router.get("/assessments/{assessment_id}", response_model=schemas.AssessmentResponse)
def get_assessment(
    assessment_id: int,
    ctx: CompanyContext = Depends(require_company),
    db: Session = Depends(get_db),
) -> schemas.AssessmentResponse:
    """Return a single assessment owned by the active company (Req 4.2, 4.3)."""
    repo = AssessmentRepository(db)
    assessment = repo.get(assessment_id, ctx.company_id)
    if assessment is None:
        raise NotFoundError(f"Assessment {assessment_id} was not found.")
    return _to_response(assessment)


@router.post(
    "/assessments/{assessment_id}/remediation",
    response_model=schemas.RemediationPlanResponse,
)
def generate_remediation(
    assessment_id: int,
    ctx: CompanyContext = Depends(require_company),
    db: Session = Depends(get_db),
) -> schemas.RemediationPlanResponse:
    """Generate (and cache) a remediation plan for this company's assessment."""
    repo = AssessmentRepository(db)
    assessment = repo.get(assessment_id, ctx.company_id)
    if assessment is None:
        raise NotFoundError(f"Assessment {assessment_id} was not found.")

    gaps = [schemas.Gap(**gap) for gap in assessment.gaps]
    plan = generate_remediation_plan(
        gaps,
        overall_score=assessment.overall_score,
        domain_scores=assessment.domain_scores,
        answers=assessment.answers,
    )
    repo.update_remediation(assessment_id, ctx.company_id, plan.model_dump())
    return plan


@router.get(
    "/assessments/{assessment_id}/remediation",
    response_model=schemas.RemediationPlanResponse,
)
def get_remediation(
    assessment_id: int,
    ctx: CompanyContext = Depends(require_company),
    db: Session = Depends(get_db),
) -> schemas.RemediationPlanResponse:
    """Return (or generate) this company's cached remediation plan."""
    repo = AssessmentRepository(db)
    assessment = repo.get(assessment_id, ctx.company_id)
    if assessment is None:
        raise NotFoundError(f"Assessment {assessment_id} was not found.")

    if assessment.remediation_plan:
        return schemas.RemediationPlanResponse(**assessment.remediation_plan)

    gaps = [schemas.Gap(**gap) for gap in assessment.gaps]
    plan = generate_remediation_plan(
        gaps,
        overall_score=assessment.overall_score,
        domain_scores=assessment.domain_scores,
        answers=assessment.answers,
    )
    repo.update_remediation(assessment_id, ctx.company_id, plan.model_dump())
    return plan


@router.get("/assessments/{assessment_id}/report")
def export_report(
    assessment_id: int,
    format: str = "markdown",
    ctx: CompanyContext = Depends(require_company),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Export a Markdown report for this company's assessment (Req 6)."""
    normalized = (format or "markdown").lower()
    if normalized not in ("markdown", "pdf"):
        raise ValidationError(
            f"Unsupported report format '{format}'. Supported formats: markdown."
        )
    if normalized == "pdf":
        raise ValidationError(
            "PDF export is not available. Please request the markdown format."
        )

    repo = AssessmentRepository(db)
    assessment = repo.get(assessment_id, ctx.company_id)
    if assessment is None:
        raise NotFoundError(f"Assessment {assessment_id} was not found.")

    gaps = [schemas.Gap(**gap) for gap in assessment.gaps]
    plan = (
        schemas.RemediationPlanResponse(**assessment.remediation_plan)
        if assessment.remediation_plan
        else None
    )
    report = render_markdown_report(
        assessment_id=assessment.id,
        created_at=assessment.created_at,
        overall_score=assessment.overall_score,
        domain_scores=assessment.domain_scores,
        gaps=gaps,
        remediation_plan=plan,
    )
    filename = f"complypk-assessment-{assessment.id}.md"
    return PlainTextResponse(
        content=report,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
