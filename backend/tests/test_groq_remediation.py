"""Tests for the Groq-backed remediation path and its fallback behavior.

The Groq HTTP call is stubbed (no real network). We verify: a validated response
yields source="llm"; any error/rate-limit/invalid/incomplete/missing-key case
degrades to the deterministic template fallback (source="fallback"); and the
request contains only non-personal data.
"""

from __future__ import annotations

import json

import app.services.remediation_service as rs
from app.config import Settings
from app.schemas import Gap


def _settings(model="llama-3.1-8b-instant", key="test-key"):
    return Settings(
        allowed_frontend_origin="http://localhost:5173",
        database_url="sqlite:///./x.db",
        llm_api_key=None,
        groq_api_key=key,
        groq_model=model,
    )


def _gaps():
    return [
        Gap(question_id="AC-1", domain="Access Control", answer="no", severity="high",
            iso_27001=["A.5.16"], nist_csf=["PR.AC-1"]),
        Gap(question_id="BR-1", domain="Backup & Recovery", answer="partial", severity="medium",
            iso_27001=[], nist_csf=[]),
    ]


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _groq_payload(steps):
    content = json.dumps({"steps": steps})
    return {"choices": [{"message": {"content": content}}]}


def test_groq_success_returns_source_llm(monkeypatch):
    payload = _groq_payload([
        {"question_id": "AC-1", "severity": "high", "action": "Enforce MFA on admin accounts."},
        {"question_id": "BR-1", "severity": "medium", "action": "Automate nightly backups and test restores."},
    ])
    monkeypatch.setattr(rs, "load_settings", lambda: _settings())
    monkeypatch.setattr(rs.httpx, "post", lambda *a, **k: _Resp(200, payload))

    plan = rs.generate_remediation_plan(_gaps(), overall_score=40,
                                        domain_scores={"Access Control": 0, "Backup & Recovery": 50},
                                        answers={"AC-1": "no", "BR-1": "partial"})
    assert plan.source == "llm"
    assert {s.question_id for s in plan.steps} == {"AC-1", "BR-1"}
    assert plan.steps[0].severity == "high"  # high first


def test_missing_key_uses_fallback_and_no_http_call(monkeypatch):
    monkeypatch.setattr(rs, "load_settings", lambda: _settings(key=None))
    def fail(*a, **k):
        raise AssertionError("httpx.post must not be called without a key")
    monkeypatch.setattr(rs.httpx, "post", fail)
    assert rs.generate_remediation_plan(_gaps()).source == "fallback"


def test_api_failure_falls_back(monkeypatch):
    monkeypatch.setattr(rs, "load_settings", lambda: _settings())
    monkeypatch.setattr(rs.httpx, "post", lambda *a, **k: _Resp(500))
    assert rs.generate_remediation_plan(_gaps()).source == "fallback"


def test_rate_limited_falls_back(monkeypatch):
    monkeypatch.setattr(rs, "load_settings", lambda: _settings())
    monkeypatch.setattr(rs.httpx, "post", lambda *a, **k: _Resp(429))
    assert rs.generate_remediation_plan(_gaps()).source == "fallback"


def test_network_error_falls_back(monkeypatch):
    monkeypatch.setattr(rs, "load_settings", lambda: _settings())
    def boom(*a, **k):
        raise rs.httpx.ConnectTimeout("timeout")
    monkeypatch.setattr(rs.httpx, "post", boom)
    assert rs.generate_remediation_plan(_gaps()).source == "fallback"


def test_invalid_json_falls_back(monkeypatch):
    bad = {"choices": [{"message": {"content": "not json"}}]}
    monkeypatch.setattr(rs, "load_settings", lambda: _settings())
    monkeypatch.setattr(rs.httpx, "post", lambda *a, **k: _Resp(200, bad))
    assert rs.generate_remediation_plan(_gaps()).source == "fallback"


def test_incomplete_coverage_falls_back(monkeypatch):
    payload = _groq_payload([
        {"question_id": "AC-1", "severity": "high", "action": "Enforce MFA."},
    ])
    monkeypatch.setattr(rs, "load_settings", lambda: _settings())
    monkeypatch.setattr(rs.httpx, "post", lambda *a, **k: _Resp(200, payload))
    assert rs.generate_remediation_plan(_gaps()).source == "fallback"


def test_safe_error_category_extracts_short_label():
    r = _Resp(401, {"error": {"type": "invalid_request_error", "code": "invalid_api_key"}})
    assert rs._safe_error_category(r) == "invalid_api_key"
    r2 = _Resp(404, {"error": {"type": "not_found_error"}})
    assert rs._safe_error_category(r2) == "not_found_error"
    r3 = _Resp(500, None)  # no JSON
    assert rs._safe_error_category(r3) == "unknown"


def test_non_200_logs_status_and_category(monkeypatch, caplog):
    import logging
    monkeypatch.setattr(rs, "load_settings", lambda: _settings())
    monkeypatch.setattr(
        rs.httpx, "post",
        lambda *a, **k: _Resp(401, {"error": {"code": "invalid_api_key"}}),
    )
    with caplog.at_level(logging.WARNING, logger="complypk"):
        plan = rs.generate_remediation_plan(_gaps())
    assert plan.source == "fallback"
    # Diagnostic present, with status + sanitized category, and no secret.
    msgs = " ".join(rec.getMessage() for rec in caplog.records)
    assert "groq_non_200" in msgs and "401" in msgs and "invalid_api_key" in msgs
    assert "test-key" not in msgs


def test_request_uses_model_and_sends_no_pii(monkeypatch):
    captured = {}
    def capture(url, *a, **k):
        captured["url"] = url
        captured["json"] = k.get("json")
        captured["headers"] = k.get("headers")
        return _Resp(200, _groq_payload([
            {"question_id": "AC-1", "severity": "high", "action": "A."},
            {"question_id": "BR-1", "severity": "medium", "action": "B."},
        ]))
    monkeypatch.setattr(rs, "load_settings", lambda: _settings(model="llama-3.1-8b-instant"))
    monkeypatch.setattr(rs.httpx, "post", capture)

    rs.generate_remediation_plan(
        _gaps(),
        overall_score=40,
        domain_scores={"Access Control": 0},
        answers={"AC-1": "no", "BR-1": "partial"},
    )
    assert captured["url"] == rs._GROQ_URL
    assert captured["json"]["model"] == "llama-3.1-8b-instant"
    # The prompt must not contain PII tokens we never pass.
    blob = json.dumps(captured["json"]).lower()
    for pii in ("email", "@", "company", "name"):
        assert pii not in blob, f"unexpected PII marker in request: {pii}"
    # Key is only in the Authorization header, not the body.
    assert "test-key" not in blob
    assert captured["headers"]["Authorization"] == "Bearer test-key"
