"""API tests for questionnaire and assessment routes (now company-scoped).

Questionnaire is public (static content). Assessment endpoints require an
authenticated, company-scoped client (``company_a`` fixture).
"""

from __future__ import annotations

from app.services.content_loader import load_questions

QUESTIONS = load_questions()


def _valid_answers(value: str = "yes") -> dict[str, str]:
    return {q.id: value for q in QUESTIONS}


def test_get_questionnaire_groups_by_domain(client):
    resp = client.get("/api/questionnaire")
    assert resp.status_code == 200
    domains = resp.json()["domains"]
    expected_domains = {q.domain for q in QUESTIONS}
    assert set(domains.keys()) == expected_domains
    total = sum(len(items) for items in domains.values())
    assert total == len(QUESTIONS)


def test_assessments_require_authentication(client):
    # No session cookie -> 401.
    assert client.get("/api/assessments").status_code == 401
    assert client.post("/api/assessments", json={"answers": _valid_answers()}).status_code == 401


def test_empty_history_returns_200_empty_list(company_a):
    resp = company_a.get("/api/assessments")
    assert resp.status_code == 200
    assert resp.json() == []


def test_submit_assessment_persists_and_returns(company_a):
    resp = company_a.post("/api/assessments", json={"answers": _valid_answers("yes")})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] is not None
    assert body["overall_score"] == 100
    assert body["gaps"] == []
    assert "readiness assessment" in body["disclaimer"].lower()

    fetched = company_a.get("/api/assessments/" + str(body["id"]))
    assert fetched.status_code == 200
    assert fetched.json()["overall_score"] == 100


def test_submit_missing_question_is_rejected_without_persistence(company_a):
    answers = _valid_answers("yes")
    answers.pop(QUESTIONS[0].id)
    resp = company_a.post("/api/assessments", json={"answers": answers})
    assert resp.status_code == 422
    assert "error_ref" in resp.json()
    assert company_a.get("/api/assessments").json() == []


def test_submit_unknown_question_is_rejected(company_a):
    answers = _valid_answers("yes")
    answers["ZZ-99"] = "no"
    resp = company_a.post("/api/assessments", json={"answers": answers})
    assert resp.status_code == 422
    assert company_a.get("/api/assessments").json() == []


def test_submit_invalid_answer_value_is_422(company_a):
    answers = _valid_answers("yes")
    answers[QUESTIONS[0].id] = "maybe"
    resp = company_a.post("/api/assessments", json={"answers": answers})
    assert resp.status_code == 422


def test_unknown_assessment_id_returns_404(company_a):
    resp = company_a.get("/api/assessments/999999")
    assert resp.status_code == 404
    assert "error_ref" in resp.json()


def test_invalid_assessment_id_type_returns_422(company_a):
    resp = company_a.get("/api/assessments/not-an-int")
    assert resp.status_code == 422


def test_history_ordering_most_recent_first(company_a):
    first = company_a.post("/api/assessments", json={"answers": _valid_answers("no")}).json()
    second = company_a.post("/api/assessments", json={"answers": _valid_answers("yes")}).json()
    history = company_a.get("/api/assessments").json()
    ids = [row["id"] for row in history]
    assert ids[0] == max(first["id"], second["id"])
    assert ids[-1] == min(first["id"], second["id"])
