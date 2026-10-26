"""Gap-mapping service: classify failed answers as gaps and attach controls.

A question answered "no" or "partial" is a Gap; "yes" is never a Gap (Req 3.1).
Each Gap is assigned a Severity ("no" -> "high", "partial" -> "medium",
Req 3.3) and the ISO 27001 / NIST CSF references defined for its question in the
control mapping, using empty lists where a question or standard is unmapped
(Req 3.2, 3.5).

Returns Pydantic :class:`app.schemas.Gap` instances so gaps serialize
consistently across persistence and API responses.

Layering: this is a service and depends only on the content loader and schemas;
it has no upward dependency on routers (Req 12.2).
"""

from __future__ import annotations

from app.schemas import Gap
from app.services.content_loader import ControlRefs, Question

# Severity assigned by answer value (Req 3.3). "yes" answers are not gaps.
_SEVERITY_BY_ANSWER: dict[str, str] = {"no": "high", "partial": "medium"}


def build_gaps(
    answers: dict[str, str],
    questions: list[Question],
    control_mapping: dict[str, ControlRefs],
) -> list[Gap]:
    """Build the list of gaps for a set of answers (Req 3.1, 3.2, 3.3, 3.5).

    Args:
        answers: Mapping of ``question_id -> answer value`` for every question.
        questions: The loaded questionnaire (provides each question's domain).
        control_mapping: Mapping of ``question_id -> ControlRefs``; questions
            absent from this mapping yield empty reference lists.

    Returns:
        A list of :class:`app.schemas.Gap`, one per question answered "no" or
        "partial", in questionnaire order.
    """
    gaps: list[Gap] = []

    for question in questions:
        answer = answers[question.id]
        severity = _SEVERITY_BY_ANSWER.get(answer)
        if severity is None:
            # "yes" (or anything not failing) is not a gap (Req 3.1).
            continue

        refs = control_mapping.get(question.id)
        iso_refs = list(refs.iso_27001) if refs is not None else []
        nist_refs = list(refs.nist_csf) if refs is not None else []

        gaps.append(
            Gap(
                question_id=question.id,
                domain=question.domain,
                answer=answer,
                severity=severity,
                iso_27001=iso_refs,
                nist_csf=nist_refs,
            )
        )

    return gaps
