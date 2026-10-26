"""Tests for remediation (Req 5), report export (Req 6), and demo (Req 7).

Assessment-dependent endpoints use an authenticated company client; the demo
endpoint is public sample data.
"""

from __future__ import annotations

from app.services.content_loader import load_questions

QUESTIONS = load_questions()


def _answers(value: str) -> dict[str, str]:
    return {q.id: value for q in QUESTIONS}


def _create_assessment(cc, value: str = "no") -> int:
    resp = cc.post("/api/assessments", json={"answers": _answers(value)})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- Remediation (Req 5) -----------------------------------------------------

def test_remediation_covers_every_gap_and_orders_by_severity(company_a):
    answers = {}
    for i, q in enumerate(QUESTIONS):
        answers[q.id] = ("no", "partial", "yes")[i % 3]
    aid = company_a.post("/api/assessments", json={"answers": answers}).json()["id"]

    resp = company_a.post("/api/assessments/" + str(aid) + "/remediation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] in ("llm", "fallback")

    gap_ids = {qid for qid, a in answers.items() if a in ("no", "partial")}
    step_ids = {s["question_id"] for s in body["steps"]}
    assert gap_ids <= step_ids

    order = {"high": 0, "medium": 1, "low": 2}
    keys = [order[s["severity"]] for s in body["steps"]]
    assert keys == sorted(keys)
    assert "readiness assessment" in body["disclaimer"].lower()


def test_remediation_unknown_id_returns_404(company_a):
    resp = company_a.post("/api/assessments/999999/remediation")
    assert resp.status_code == 404


def test_get_remediation_generates_when_absent(company_a):
    aid = _create_assessment(company_a, "no")
    resp = company_a.get("/api/assessments/" + str(aid) + "/remediation")
    assert resp.status_code == 200
    assert len(resp.json()["steps"]) > 0


# --- Report export (Req 6) ---------------------------------------------------

def test_report_markdown_contains_required_sections_and_disclaimer(company_a):
    aid = _create_assessment(company_a, "no")
    resp = company_a.get("/api/assessments/" + str(aid) + "/report")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    text = resp.text
    assert "Overall readiness score" in text
    assert "Domain scores" in text
    assert "Identified gaps" in text
    assert "Remediation plan" in text
    assert "readiness assessment only" in text.lower()
    lowered = text.lower()
    assert "certified" not in lowered
    assert "guaranteed compliance" not in lowered


def test_report_default_is_markdown(company_a):
    aid = _create_assessment(company_a, "yes")
    resp = company_a.get("/api/assessments/" + str(aid) + "/report")
    assert resp.status_code == 200
    assert "ComplyPK Readiness Assessment Report" in resp.text


def test_report_invalid_format_returns_422(company_a):
    aid = _create_assessment(company_a, "yes")
    resp = company_a.get("/api/assessments/" + str(aid) + "/report", params={"format": "docx"})
    assert resp.status_code == 422


def test_report_pdf_not_available_returns_422(company_a):
    aid = _create_assessment(company_a, "yes")
    resp = company_a.get("/api/assessments/" + str(aid) + "/report", params={"format": "pdf"})
    assert resp.status_code == 422


def test_report_unknown_id_returns_404(company_a):
    resp = company_a.get("/api/assessments/999999/report")
    assert resp.status_code == 404


# --- Demo mode (Req 7) — public sample data ---------------------------------

def test_demo_returns_profile_and_valid_answers(client):
    resp = client.get("/api/demo")
    assert resp.status_code == 200
    body = resp.json()
    assert "company" in body and body["company"]
    assert set(body["answers"].keys()) == {q.id for q in QUESTIONS}
    assert all(v in ("yes", "partial", "no") for v in body["answers"].values())


def test_demo_answers_submit_successfully(company_a):
    demo = company_a.raw().get("/api/demo").json()
    resp = company_a.post("/api/assessments", json={"answers": demo["answers"]})
    assert resp.status_code == 201
