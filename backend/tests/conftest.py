"""Shared pytest fixtures.

Provides an isolated SQLite database per test and a FastAPI ``TestClient`` with
the ``get_db`` dependency overridden to use that database, so tests never touch
the real ``complypk.db`` file.

``ALLOWED_FRONTEND_ORIGIN`` is set before importing application modules because
config is validated at import time (Req 9.1, 9.4).
"""

from __future__ import annotations

import os

os.environ.setdefault("ALLOWED_FRONTEND_ORIGIN", "http://localhost:5173")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (register all tables on Base.metadata)
from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    """Create a fresh in-memory database and yield a session factory."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield testing_session
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    """A TestClient whose get_db dependency uses the in-memory database."""
    from fastapi.testclient import TestClient

    def _override_get_db():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- Auth / tenancy helpers --------------------------------------------------


class CompanyClient:
    """A thin wrapper that injects auth cookie, CSRF header, and company id.

    The session cookie is managed by the underlying TestClient cookie jar; we add
    the CSRF token (for unsafe methods) and the X-Company-Id header automatically.
    """

    def __init__(self, client, csrf_token: str, company_id: int | None):
        self._c = client
        self._csrf = csrf_token
        self.company_id = company_id

    def _headers(self, extra=None):
        h = {"X-CSRF-Token": self._csrf}
        if self.company_id is not None:
            h["X-Company-Id"] = str(self.company_id)
        if extra:
            h.update(extra)
        return h

    def get(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._c.get(url, **kw)

    def post(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._c.post(url, **kw)

    def put(self, url, **kw):
        kw.setdefault("headers", {}).update(self._headers())
        return self._c.put(url, **kw)

    def raw(self):
        return self._c


def _make_authed_client(db_session, email: str, password: str = "password123"):
    """Register + log in a fresh user on its own TestClient (own cookie jar)."""
    from fastapi.testclient import TestClient

    def _override_get_db():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    tc = TestClient(app)
    tc.__enter__()
    tc.post("/api/auth/register", json={"email": email, "password": password})
    login = tc.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    csrf = login.json()["csrf_token"]
    return tc, csrf


@pytest.fixture()
def company_factory(db_session):
    """Factory: create an authenticated user with a new company (admin).

    Returns a callable ``make(email, company_name)`` -> CompanyClient. All
    created TestClients share the same in-memory DB via the dependency override.
    """
    created = []

    def make(email: str, company_name: str) -> CompanyClient:
        tc, csrf = _make_authed_client(db_session, email)
        created.append(tc)
        resp = tc.post(
            "/api/companies",
            json={"name": company_name},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201, resp.text
        company_id = resp.json()["company_id"]
        return CompanyClient(tc, csrf, company_id)

    yield make

    for tc in created:
        try:
            tc.__exit__(None, None, None)
        except Exception:
            pass
    app.dependency_overrides.clear()


@pytest.fixture()
def company_a(company_factory):
    return company_factory("alice@acme.example", "Acme Corp")


@pytest.fixture()
def company_b(company_factory):
    return company_factory("bob@globex.example", "Globex Inc")


@pytest.fixture()
def seed_legacy(db_session):
    """Insert an unowned (legacy) assessment + profile directly into the DB.

    Simulates records created before multi-tenancy (company_id is NULL).
    Returns a callable that creates one legacy pair and returns their ids.
    """
    from app.models.assessment import Assessment
    from app.models.company_profile import CompanyProfile

    def seed():
        db = db_session()
        try:
            a = Assessment(
                company_id=None,
                answers={}, overall_score=50, domain_scores={}, gaps=[],
                remediation_plan=None, company=None,
            )
            p = CompanyProfile(company_id=None, name="Legacy Co")
            db.add(a)
            db.add(p)
            db.commit()
            return a.id, p.id
        finally:
            db.close()

    return seed
