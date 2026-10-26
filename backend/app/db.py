"""Database engine, session, and declarative base wiring.

Creates the SQLAlchemy engine and session factory from the resolved
``DATABASE_URL`` (via :func:`app.config.load_settings`). SQLite URLs receive
``connect_args={"check_same_thread": False}`` so the connection can be shared
across FastAPI's threaded request handling (Req 9.2, 9.3).

Layering: this is infrastructure that models and repositories build on. It
depends only on configuration and SQLAlchemy; it has no upward dependency on
services or routers (Req 12.2).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings, load_settings


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


def _make_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for the given connection string.

    SQLite connections need ``check_same_thread=False`` to be usable from the
    threads FastAPI uses to service requests. Other backends (e.g. PostgreSQL)
    use their driver defaults.
    """
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(
        database_url,
        connect_args=connect_args,
        future=True,
    )


# Resolve configuration once at import time and build the shared engine and
# session factory from it. ``load_settings`` fails fast on invalid config.
_settings: Settings = load_settings()
engine: Engine = _make_engine(_settings.database_url)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
    future=True,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a database session and closes it.

    Usage::

        @router.get("/items")
        def read_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_column_if_missing(table: str, column: str, ddl_type: str) -> None:
    """Safely add a nullable column to an existing table if it is absent.

    ``create_all`` creates new tables but never alters existing ones. This
    performs an additive ``ADD COLUMN`` (nullable, no default) so existing rows
    are preserved untouched (Req 5). It is a no-op when the table or column
    already exists and works on both SQLite and PostgreSQL. Identifiers are
    fixed literals supplied by application code, never user input.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if not inspector.has_table(table):
        return  # create_all will build it fresh with all columns.
    columns = {col["name"] for col in inspector.get_columns(table)}
    if column in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def init_db() -> None:
    """Create all tables and apply safe additive column migrations.

    Models must be imported before calling this so their tables are registered
    on ``Base.metadata``. Additive column migrations run before create_all so a
    legacy table gains new columns; create_all then adds any new tables (users,
    companies, memberships, sessions) without touching existing data (Req 5).
    """
    # Import models for their side effect of registering tables on Base.metadata.
    from app import models  # noqa: F401  (registration side effect)

    # Legacy column additions (idempotent, non-destructive).
    _add_column_if_missing("assessments", "company", "JSON")
    _add_column_if_missing("assessments", "company_id", "INTEGER")
    _add_column_if_missing("company_profiles", "company_id", "INTEGER")
    # Email verification flag for invitation acceptance (default 0 = unverified).
    _add_column_if_missing("users", "email_verified", "BOOLEAN NOT NULL DEFAULT 0")

    Base.metadata.create_all(bind=engine)
