"""Cross-tenant security tests: Company A must never access Company B's data.

Uses two separate companies/users (company_a, company_b fixtures). Verifies that
authorization is enforced server-side from the session + membership, not from any
client-supplied company id.
"""

from __future__ import annotations

from app.services.content_loader import load_questions

QUESTIONS = load_questions()


def _answers(value="no"):
    return {q.id: value for q in QUESTIONS}


def _create(cc, value="no"):
    r = cc.post("/api/assessments", json={"answers": _answers(value)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_user_sees_only_own_company_data(company_a, company_b):
    a_id = _create(company_a, "no")
    b_id = _create(company_b, "yes")

    a_hist = {row["id"] for row in company_a.get("/api/assessments").json()}
    b_hist = {row["id"] for row in company_b.get("/api/assessments").json()}
    assert a_id in a_hist and a_id not in b_hist
    assert b_id in b_hist and b_id not in a_hist


def test_cannot_fetch_other_companys_assessment_by_id(company_a, company_b):
    b_id = _create(company_b, "yes")
    # A guesses B's assessment id -> 404 (no data leaked).
    resp = company_a.get("/api/assessments/" + str(b_id))
    assert resp.status_code == 404


def test_cannot_access_other_companys_remediation(company_a, company_b):
    b_id = _create(company_b, "no")
    assert company_a.post("/api/assessments/" + str(b_id) + "/remediation").status_code == 404
    assert company_a.get("/api/assessments/" + str(b_id) + "/remediation").status_code == 404


def test_cannot_export_other_companys_report(company_a, company_b):
    b_id = _create(company_b, "no")
    assert company_a.get("/api/assessments/" + str(b_id) + "/report").status_code == 404


def test_spoofed_company_header_is_rejected(company_a, company_b):
    # A authenticates but sends B's company id in the header.
    b_cid = company_b.company_id
    a_id = _create(company_a, "no")
    # Forge the X-Company-Id header to B's company.
    resp = company_a.raw().get(
        "/api/assessments",
        headers={"X-CSRF-Token": company_a._csrf, "X-Company-Id": str(b_cid)},
    )
    # A is not a member of B -> 403, and never B's data.
    assert resp.status_code == 403


def test_nonmember_cannot_access_company_without_membership(company_a):
    # A user with a session but targeting a company they don't belong to.
    resp = company_a.raw().get(
        "/api/assessments",
        headers={"X-CSRF-Token": company_a._csrf, "X-Company-Id": "999999"},
    )
    assert resp.status_code == 403


def test_unauthenticated_cannot_access_company_data(client):
    assert client.get("/api/assessments").status_code == 401
    assert client.get("/api/company").status_code == 401


def test_company_profiles_are_isolated(company_a, company_b):
    company_a.post("/api/company", json={"name": "Acme Profile"})
    company_b.post("/api/company", json={"name": "Globex Profile"})
    assert company_a.get("/api/company").json()["name"] == "Acme Profile"
    assert company_b.get("/api/company").json()["name"] == "Globex Profile"


def test_csrf_required_for_state_changing_requests(company_a):
    # POST without the CSRF header must be rejected (403), even with a session.
    resp = company_a.raw().post(
        "/api/assessments",
        json={"answers": _answers("yes")},
        headers={"X-Company-Id": str(company_a.company_id)},  # no X-CSRF-Token
    )
    assert resp.status_code == 403
