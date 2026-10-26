"""Focused example tests for the gap-mapping service (Req 3.1, 3.2, 3.3, 3.5)."""

from __future__ import annotations

from app.services.content_loader import (
    ControlRefs,
    load_control_mapping,
    load_questions,
)
from app.services.gap_mapping_service import build_gaps

QUESTIONS = load_questions()
MAPPING = load_control_mapping()


def test_yes_answers_produce_no_gaps():
    answers = {q.id: "yes" for q in QUESTIONS}
    gaps = build_gaps(answers, QUESTIONS, MAPPING)
    assert gaps == []


def test_gap_classification_matches_failing_answers():
    answers = {}
    for i, q in enumerate(QUESTIONS):
        answers[q.id] = ("yes", "partial", "no")[i % 3]
    gaps = build_gaps(answers, QUESTIONS, MAPPING)

    failing_ids = {qid for qid, a in answers.items() if a in ("no", "partial")}
    assert {g.question_id for g in gaps} == failing_ids


def test_severity_rule_no_is_high_partial_is_medium():
    answers = {q.id: "no" for q in QUESTIONS}
    first = QUESTIONS[0].id
    answers[first] = "partial"
    gaps = {g.question_id: g for g in build_gaps(answers, QUESTIONS, MAPPING)}
    assert gaps[first].severity == "medium"
    for qid, gap in gaps.items():
        if qid != first:
            assert gap.severity == "high"


def test_control_refs_match_mapping():
    answers = {q.id: "no" for q in QUESTIONS}
    gaps = {g.question_id: g for g in build_gaps(answers, QUESTIONS, MAPPING)}
    for qid, gap in gaps.items():
        refs = MAPPING.get(qid)
        if refs is None:
            assert gap.iso_27001 == []
            assert gap.nist_csf == []
        else:
            assert gap.iso_27001 == list(refs.iso_27001)
            assert gap.nist_csf == list(refs.nist_csf)


def test_unmapped_question_yields_empty_refs():
    # A question not present in the mapping must yield empty reference lists.
    answers = {q.id: "no" for q in QUESTIONS}
    partial_mapping = {QUESTIONS[0].id: ControlRefs(iso_27001=("A.1",), nist_csf=())}
    gaps = {g.question_id: g for g in build_gaps(answers, QUESTIONS, partial_mapping)}
    assert gaps[QUESTIONS[0].id].iso_27001 == ["A.1"]
    assert gaps[QUESTIONS[1].id].iso_27001 == []
    assert gaps[QUESTIONS[1].id].nist_csf == []
