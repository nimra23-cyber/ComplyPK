"""Questionnaire router: serve the questionnaire grouped by domain (Req 1).

Loads the questionnaire via the content loader and groups questions under their
domains. A content-file problem surfaces as :class:`ContentError`, which the
centralized handler renders as HTTP 500 without leaking details (Req 1.4, 1.5).
"""

from __future__ import annotations

from fastapi import APIRouter

from app import schemas
from app.services.content_loader import load_questions

router = APIRouter(prefix="/api", tags=["questionnaire"])


@router.get("/questionnaire", response_model=schemas.QuestionnaireResponse)
def get_questionnaire() -> schemas.QuestionnaireResponse:
    """Return the questionnaire grouped by domain (Req 1.1, 1.2, 1.3)."""
    questions = load_questions()

    domains: dict[str, list[schemas.Question]] = {}
    for q in questions:
        domains.setdefault(q.domain, []).append(
            schemas.Question(
                id=q.id,
                domain=q.domain,
                text=q.text,
                allowed_answers=list(q.allowed_answers),
            )
        )

    return schemas.QuestionnaireResponse(domains=domains)
