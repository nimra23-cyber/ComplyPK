"""Focused example tests for the scoring service (Req 2.1, 2.2, 2.3)."""

from __future__ import annotations

from app.services.content_loader import load_questions
from app.services.scoring_service import (
    compute_domain_scores,
    compute_overall_score,
)

QUESTIONS = load_questions()


def _answers(value: str) -> dict[str, str]:
    return {q.id: value for q in QUESTIONS}


def test_all_yes_scores_100():
    assert compute_overall_score(_answers("yes"), QUESTIONS) == 100


def test_all_no_scores_0():
    assert compute_overall_score(_answers("no"), QUESTIONS) == 0


def test_all_partial_scores_50():
    assert compute_overall_score(_answers("partial"), QUESTIONS) == 50


def test_overall_score_within_bounds_for_mixed_answers():
    answers = {}
    for i, q in enumerate(QUESTIONS):
        answers[q.id] = ("yes", "partial", "no")[i % 3]
    score = compute_overall_score(answers, QUESTIONS)
    assert 0 <= score <= 100


def test_domain_scores_cover_all_domains_and_are_bounded():
    scores = compute_domain_scores(_answers("partial"), QUESTIONS)
    expected_domains = {q.domain for q in QUESTIONS}
    assert set(scores.keys()) == expected_domains
    for value in scores.values():
        assert 0 <= value <= 100
    # All-partial means every domain is exactly 50.
    assert all(v == 50 for v in scores.values())


def test_domain_scores_all_yes_are_100():
    scores = compute_domain_scores(_answers("yes"), QUESTIONS)
    assert all(v == 100 for v in scores.values())
