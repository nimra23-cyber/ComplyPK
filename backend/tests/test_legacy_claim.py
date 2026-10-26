"""Tests for legacy-data claiming: status, authorization, repeatability, ownership."""

from __future__ import annotations


def test_legacy_status_reports_counts(company_a, seed_legacy):
    seed_legacy()
    resp = company_a.get("/api/company/legacy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["unowned_assessments"] >= 1
    assert body["unowned_profiles"] >= 1


def test_admin_can_claim_legacy_and_records_become_owned(company_a, seed_legacy):
    a_id, _p_id = seed_legacy()

    # Before claim: the legacy assessment is not visible to the company.
    assert company_a.get("/api/assessments/" + str(a_id)).status_code == 404

    resp = company_a.post("/api/company/legacy/claim")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["claimed_assessments"] >= 1
    assert body["claimed_profiles"] >= 1

    # After claim: the record now belongs to company A and is visible.
    assert company_a.get("/api/assessments/" + str(a_id)).status_code == 200
    # And it appears in history.
    ids = {r["id"] for r in company_a.get("/api/assessments").json()}
    assert a_id in ids


def test_repeated_claim_is_safe_and_idempotent(company_a, seed_legacy):
    seed_legacy()
    first = company_a.post("/api/company/legacy/claim").json()
    assert first["claimed_assessments"] >= 1
    # Second claim finds nothing left to claim.
    second = company_a.post("/api/company/legacy/claim").json()
    assert second["claimed_assessments"] == 0
    assert second["claimed_profiles"] == 0


def test_claim_does_not_take_another_companys_records(company_a, company_b, seed_legacy):
    seed_legacy()
    # A claims the legacy data.
    company_a.post("/api/company/legacy/claim")
    # B then claims — must get nothing (records already owned by A).
    res_b = company_b.post("/api/company/legacy/claim").json()
    assert res_b["claimed_assessments"] == 0
    assert res_b["claimed_profiles"] == 0


def test_member_cannot_claim_legacy(company_factory, company_a, seed_legacy):
    seed_legacy()
    # Create a second user (with their own company) and have them JOIN company A
    # as a member, then attempt to claim while scoped to company A.
    member = company_factory("member@acme.example", "Member Temp Co")
    # The member joins company A (becomes role=member there).
    join = member.raw().post(
        "/api/companies/join",
        json={"company_id": company_a.company_id},
        headers={"X-CSRF-Token": member._csrf},
    )
    assert join.status_code == 200, join.text
    assert join.json()["role"] == "member"

    # Acting as a member of company A, claiming must be forbidden (admin only).
    resp = member.raw().post(
        "/api/company/legacy/claim",
        headers={"X-CSRF-Token": member._csrf, "X-Company-Id": str(company_a.company_id)},
    )
    assert resp.status_code == 403


def test_claim_requires_authentication(client):
    assert client.post("/api/company/legacy/claim").status_code == 401
