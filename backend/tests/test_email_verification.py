"""Tests for the secure email-verification flow.

Key security property: a user CANNOT mark their own email verified without the
emailed token. The raw token is never returned by the API; request-verification
only emails it (and fails clearly if SMTP is unconfigured).
"""

from __future__ import annotations

import app.routers.auth as auth_router
from app.config import load_settings


def test_new_user_is_unverified(company_a):
    # company_a's admin just registered; email should be unverified by default.
    me = company_a.get("/api/auth/me").json()
    assert me["email_verified"] is False


def test_request_verification_requires_smtp(company_a):
    # No SMTP configured -> clear 503, and nothing gets verified.
    r = company_a.post("/api/auth/request-verification")
    assert r.status_code == 503
    assert company_a.get("/api/auth/me").json()["email_verified"] is False


def test_request_verification_does_not_return_token(company_a, monkeypatch):
    base = load_settings({"ALLOWED_FRONTEND_ORIGIN": "http://localhost:5173",
                          "SMTP_HOST": "smtp.example", "SMTP_FROM": "no-reply@example"})
    monkeypatch.setattr(auth_router, "load_settings", lambda: base)
    captured = {}
    def fake_send(settings, recipient, raw_token):
        captured["token"] = raw_token  # only the email channel sees it
    monkeypatch.setattr(auth_router, "send_verification_email", fake_send)

    r = company_a.post("/api/auth/request-verification")
    assert r.status_code == 200
    # The response body must NOT contain the raw token.
    assert "token" not in r.json()
    assert captured.get("token")  # the email path received a token

    # Still unverified until the emailed token is redeemed.
    assert company_a.get("/api/auth/me").json()["email_verified"] is False


def test_invalid_verification_token_rejected(company_a):
    r = company_a.post("/api/auth/verify-email", json={"token": "x" * 40})
    assert r.status_code == 422
    assert company_a.get("/api/auth/me").json()["email_verified"] is False


def test_verify_email_with_emailed_token_succeeds(company_a, monkeypatch):
    base = load_settings({"ALLOWED_FRONTEND_ORIGIN": "http://localhost:5173",
                          "SMTP_HOST": "smtp.example", "SMTP_FROM": "no-reply@example"})
    monkeypatch.setattr(auth_router, "load_settings", lambda: base)
    captured = {}
    def fake_send(settings, recipient, raw_token):
        captured["token"] = raw_token
    monkeypatch.setattr(auth_router, "send_verification_email", fake_send)

    assert company_a.post("/api/auth/request-verification").status_code == 200
    token = captured["token"]
    # Redeem the emailed token.
    r = company_a.post("/api/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text
    assert r.json()["email_verified"] is True
    assert company_a.get("/api/auth/me").json()["email_verified"] is True
    # Token is single-use: redeeming again fails.
    assert company_a.post("/api/auth/verify-email", json={"token": token}).status_code == 422
