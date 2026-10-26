"""Scoring service: compute overall and per-domain readiness scores.

Pure functions over the submitted answers and the loaded questionnaire. Weights
are ``yes=1.0``, ``partial=0.5``, ``no=0.0``; the Overall_Score is
``round(sum(weights) / 20 * 100)`` and each Domain_Score is
``round(sum(domain weights) / domain question count * 100)`` (Req 2.1, 2.2, 2.3).

Domain question counts are derived from the loaded questionnaire rather than
hard-coded, so content edits in ``questions.json`` remain the single source of
truth.

Layering: this is a service and depends only on the content loader and the
standard library; it has no upward dependency on routers (Req 12.2).
"""

from __future__ import annotations

from app.services.content_loader import Question

# Answer weights used for scoring (Req 2.3).
_ANSWER_WEIGHTS: dict[str, float] = {"yes": 1.0, "partial": 0.5, "no": 0.0}


def _clamp_score(value: float) -> int:
    """Round to the nearest integer and clamp into the inclusive range [0, 100]."""
    return max(0, min(100, round(value)))


def compute_overall_score(answers: dict[str, str], questions: list[Question]) -> int:
    """Compute the Overall_Score from all answers (Req 2.1, 2.3).

    Args:
        answers: Mapping of ``question_id -> answer value``. Must contain exactly
            one valid answer for each question in ``questions``.
        questions: The loaded questionnaire (used to determine the denominator).

    Returns:
        An integer in [0, 100].
    """
    total_weight = sum(_ANSWER_WEIGHTS[answers[q.id]] for q in questions)
    denominator = len(questions)
    if denominator == 0:
        return 0
    return _clamp_score(total_weight / denominator * 100)


def compute_domain_scores(
    answers: dict[str, str], questions: list[Question]
) -> dict[str, int]:
    """Compute a Domain_Score for each domain in the questionnaire (Req 2.2, 2.3).

    Args:
        answers: Mapping of ``question_id -> answer value`` for every question.
        questions: The loaded questionnaire.

    Returns:
        Mapping of domain name -> integer score in [0, 100], one entry per domain
        present in the questionnaire.
    """
    domain_weight_totals: dict[str, float] = {}
    domain_counts: dict[str, int] = {}

    for q in questions:
        domain_weight_totals[q.domain] = (
            domain_weight_totals.get(q.domain, 0.0) + _ANSWER_WEIGHTS[answers[q.id]]
        )
        domain_counts[q.domain] = domain_counts.get(q.domain, 0) + 1

    return {
        domain: _clamp_score(domain_weight_totals[domain] / domain_counts[domain] * 100)
        for domain in domain_weight_totals
    }
