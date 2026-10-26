"""Tests for company profile (tenant-scoped) and assessment association."""

from __future__ import annotations

from app.services.content_loader import load_questions

QUESTIONS = load_questions()


def _answers(value="yes"):
    return {q.id: value for q in QUESTIONS}


def test_company_profile_requires_auth(client):
    assert client.get("/api/company").status_code == 401


def test_get_company_404_when_none(company_a):
    assert company_a.get("/api/company").status_code == 404


def test_create_company_requires_name(company_a):
    resp = company_a.post("/api/company", json={"industry": "Fintech"})
    assert resp.status_code == 422


def test_create_company_rejects_invalid_email(company_a):
    resp = company_a.post("/api/company", json={"name": "Acme", "contact_email": "not-an-email"})
    assert resp.status_code == 422


def test_create_and_get_company(company_a):
    payload = {
        "name": "Acme Technologies",
        "industry": "Fintech",
        "size": "51-200",
        "country": "Pakistan",
        "contact_email": "security@acme.example",
    }
    created = company_a.post("/api/company", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Acme Technologies"

    fetched = company_a.get("/api/company")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Acme Technologies"
    assert fetched.json()["contact_email"] == "security@acme.example"


def test_update_company_edits_current(company_a):
    company_a.post("/api/company", json={"name": "Old Name"})
    updated = company_a.put("/api/company", json={"name": "New Name", "country": "Pakistan"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "New Name"
    assert company_a.get("/api/company").json()["name"] == "New Name"


def test_assessment_snapshots_current_company(company_a):
    company_a.post("/api/company", json={"name": "Snapshot Co", "industry": "Health"})
    created = company_a.post("/api/assessments", json={"answers": _answers("yes")})
    assert created.status_code == 201
    body = created.json()
    assert body["company"] is not None
    assert body["company"]["name"] == "Snapshot Co"

    fetched = company_a.get("/api/assessments/" + str(body["id"]))
    assert fetched.status_code == 200
    assert fetched.json()["company"]["name"] == "Snapshot Co"


def test_editing_profile_does_not_change_past_assessment(company_a):
    company_a.post("/api/company", json={"name": "Original Co"})
    aid = company_a.post("/api/assessments", json={"answers": _answers("yes")}).json()["id"]
    company_a.put("/api/company", json={"name": "Renamed Co"})
    assert company_a.get("/api/assessments/" + str(aid)).json()["company"]["name"] == "Original Co"
