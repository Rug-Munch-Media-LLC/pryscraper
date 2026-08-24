"""Pry - engine setup and session factories.

Lazy SQLite/Postgres engine creation plus sync and async session helpers.
The module-level ``_engine`` / ``_SessionLocal`` state is the single source
of truth; the top-level ``db`` package exposes write-through aliases so
``db._engine = None`` (used by tests to force engine recreation) keeps
working unchanged.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager, contextmanager, suppress
from typing import TYPE_CHECKING, Any

try:
    from sqlalchemy import create_engine, event
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.orm import Session, sessionmaker
except ImportError:  # pragma: no cover
    pass

from db.models import _HAS_SA, Base
from pry.core.paths import PRY_DATA_DIR

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = PRY_DATA_DIR / "pry.db"

# Backward-compat aliases for existing code/tests that imported these names
_has_sqlalchemy = _HAS_SA


def get_db() -> Engine:
    """Backward-compat alias for get_engine()."""
    return get_engine()


DATABASE_URL_ENV = "PRY_DATABASE_URL"
DEFAULT_SQLITE_URL = f"sqlite:///{DEFAULT_DB_PATH}"
DEFAULT_PG_URL = "postgresql://pry:pry@localhost:5432/pry"

# Environment profiles and their default backends:
#
# | PRY_ENVIRONMENT | default backend | overrides                          |
# |-----------------|-----------------|------------------------------------|
# | dev (default)   | embedded SQLite | PRY_DATABASE_URL                   |
# | staging / prod  | Postgres        | PRY_DATABASE_URL, or               |
# |                 |                 | PRY_ALLOW_SQLITE_PROD=1 (escape    |
# |                 |                 | hatch, logs a warning)             |
#
# Rationale: silently running a production deployment on embedded SQLite
# risks data loss the moment a second replica appears. Prod/staging must
# choose Postgres *deliberately*.


def _profile() -> str:
    """Resolve the deployment profile from PRY_ENVIRONMENT."""
    env = os.getenv("PRY_ENVIRONMENT", "dev").strip().lower()
    return "prod" if env in ("prod", "production") else ("staging" if env == "staging" else "dev")


def _resolve_database_url() -> str:
    """Resolve the database URL per the environment matrix above."""
    url = os.getenv(DATABASE_URL_ENV)
    if url:
        return url

    if _profile() in ("prod", "staging"):
        if os.getenv("PRY_ALLOW_SQLITE_PROD", "").strip().lower() in ("1", "true", "yes"):
            logger.warning(
                "sqlite_in_production_allowed",
                extra={"profile": _profile(), "url": str(DEFAULT_DB_PATH)},
            )
            return DEFAULT_SQLITE_URL
        logger.info("database_default_postgres", extra={"profile": _profile()})
        return DEFAULT_PG_URL

    return DEFAULT_SQLITE_URL


def _resolve_async_database_url() -> str:
    """Resolve the async database URL.

    Converts ``postgresql://...`` to ``postgresql+asyncpg://...`` so the
    same resolution works for both sync and async uses. SQLite stays as
    ``sqlite+aiosqlite://...``.
    """
    url = _resolve_database_url()
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

# Async engine/session for use in async FastAPI endpoints.
# These are lazily initialized alongside the sync engine.
_async_engine: Any = None  # AsyncEngine (type is Any to avoid import-order issues)
_async_session_local: Any = None  # async_sessionmaker[AsyncSession]


def get_engine() -> Engine:
    """Get the SQLAlchemy engine. Lazily creates one on first call."""
    global _engine, _SessionLocal
    if not _HAS_SA:
        raise RuntimeError("sqlalchemy is not installed; pip install 'sqlalchemy>=2.0'")
    if _engine is None:
        url = _resolve_database_url()
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, connect_args=connect_args, future=True, echo=False)
        # Enable foreign keys for SQLite (off by default)
        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _enable_sqlite_fk(dbapi_conn: sqlite3.Connection, _conn_record: Any) -> None:
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
        # Auto-create tables on first import (idempotent).
        # Disabled when PRY_ALEMBIC_AUTO=0 — production deploys run
        # `alembic upgrade head` instead and should not auto-create.
        if os.environ.get("PRY_ALEMBIC_AUTO", "1") == "1":
            Base.metadata.create_all(_engine)
        logger.info(
            "db_engine_initialized", extra={"url": url.split("@")[-1] if "@" in url else url}
        )
    return _engine


def get_session() -> Session:
    """Get a new Session. Caller is responsible for closing it.

    Use `with db_session() as s:` or the `session_scope()` context manager
    for automatic cleanup and commit/rollback handling.
    """
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager: yields a Session, commits on success, rolls back on error.

    Usage:
        with session_scope() as s:
            s.add(QualityCheck(...))
            # commit happens automatically when the with-block exits cleanly
    """
    s = get_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ── Async engine / session (for async FastAPI endpoints) ──────────


def get_async_engine() -> Any:
    """Get the async SQLAlchemy engine. Lazily creates one on first call."""
    global _async_engine, _async_session_local
    if not _HAS_SA:
        raise RuntimeError("sqlalchemy is not installed; pip install 'sqlalchemy>=2.0'")
    if _async_engine is None:
        url = _resolve_async_database_url()
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _async_engine = create_async_engine(url, connect_args=connect_args, echo=False)
        _async_session_local = async_sessionmaker(
            bind=_async_engine, autoflush=False, expire_on_commit=False
        )
        logger.info(
            "db_async_engine_initialized",
            extra={"url": url.split("@")[-1] if "@" in url else url},
        )
    return _async_engine


async def get_async_session() -> AsyncSession:
    """Get a new async Session. Caller must close it.

    Prefer ``async with async_session_scope() as s:`` for automatic cleanup.
    """
    if _async_session_local is None:
        get_async_engine()
    assert _async_session_local is not None
    return _async_session_local()


@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    """Async context manager: yields an AsyncSession, commits on success,
    rolls back on error.

    Usage:
        async with async_session_scope() as s:
            result = await s.execute(select(Monitor).where(...))
    """
    s = await get_async_session()
    try:
        yield s
        await s.commit()
    except Exception:
        await s.rollback()
        raise
    finally:
        await s.close()


def dispose_engines() -> None:
    """Dispose the sync and async engine connection pools (graceful shutdown).

    Idempotent: clears module state so a subsequent get_engine()/get_async_engine()
    recreates fresh engines. Called from the FastAPI lifespan shutdown phase.
    """
    global _engine, _SessionLocal, _async_engine, _async_session_local
    for eng in (_engine, _async_engine):
        if eng is not None:
            with suppress(Exception):
                eng.dispose()
    _engine = None
    _SessionLocal = None
    _async_engine = None
    _async_session_local = None
