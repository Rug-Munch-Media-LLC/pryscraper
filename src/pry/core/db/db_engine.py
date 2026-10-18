"""Pry - engine construction and connection-pool lifecycle.

Lazy SQLite/Postgres engines (sync and async) plus the module-level state that
is the single source of truth. Session factories and schema bootstrap live in
``db_init``; both are re-exported from ``db.session``.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import suppress
from typing import TYPE_CHECKING, Any

try:
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
except ImportError:  # pragma: no cover
    logging.getLogger(__name__).warning("session_exception_handler", exc_info=True)

from pry.core.db.models import _HAS_SA
from pry.core.paths import PRY_DATA_DIR

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = PRY_DATA_DIR / "pry.db"

# Backward-compat aliases for existing code/tests that imported these names
_has_sqlalchemy = _HAS_SA

DATABASE_URL_ENV = "PRY_DATABASE_URL"
DEFAULT_SQLITE_URL = f"sqlite:///{DEFAULT_DB_PATH}"
DEFAULT_PG_URL = "postgresql://pry:pry@localhost:5432/pry"

# Profiles: dev -> embedded SQLite; staging/prod -> Postgres, unless
# PRY_ALLOW_SQLITE_PROD=1 (escape hatch, logs a warning). Silently running
# production on embedded SQLite risks data loss when a second replica appears.

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

# Guards lazy engine creation so concurrent callers cannot create duplicates.
_engine_lock = threading.Lock()

# Async engine/session for use in async FastAPI endpoints.
_async_engine: Any = None  # AsyncEngine (Any avoids import-order issues)
_async_session_local: Any = None  # async_sessionmaker[AsyncSession]


def get_db() -> Engine:
    """Backward-compat alias for get_engine()."""
    return get_engine()


def _profile() -> str:
    """Resolve the deployment profile from PRY_ENVIRONMENT."""
    env = os.getenv("PRY_ENVIRONMENT", "dev").strip().lower()
    return "prod" if env in ("prod", "production") else ("staging" if env == "staging" else "dev")


def _resolve_database_url() -> str:
    """Resolve the database URL per the environment matrix above."""
    url = os.getenv(DATABASE_URL_ENV)
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
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
    """Resolve the async database URL (Postgres -> asyncpg, SQLite -> aiosqlite)."""
    url = _resolve_database_url()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


def _connect_kwargs(url: str) -> dict[str, Any]:
    """Engine kwargs: pooled Postgres, NullPool for file-backed SQLite.

    NullPool is only safe for file-backed SQLite. Bare "sqlite://" is the
    in-memory URL (no ":memory:" token) and must keep the default pool so the
    schema created by create_all survives across connections.
    """
    if not url.startswith("sqlite"):
        return {"pool_pre_ping": True, "pool_recycle": 300}
    kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
    if ":memory:" not in url and url != "sqlite://":
        kwargs["poolclass"] = NullPool
    return kwargs


def _enable_sqlite_fk(dbapi_conn: Any, _conn_record: Any) -> None:
    """Enable foreign keys for SQLite (off by default)."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_engine() -> Engine:
    """Get the SQLAlchemy engine. Lazily creates one on first call."""
    global _engine, _SessionLocal
    if not _HAS_SA:
        raise RuntimeError("sqlalchemy is not installed; pip install 'sqlalchemy>=2.0'")
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                url = _resolve_database_url()
                _engine = create_engine(url, future=True, echo=False, **_connect_kwargs(url))
                if url.startswith("sqlite"):
                    event.listens_for(_engine, "connect")(_enable_sqlite_fk)
                _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
                # NO create_all here. Lazy engine init is not a schema
                # authority: it manufactured tables the migration chain had
                # never created, making `alembic upgrade` and runtime disagree.
                # Alembic owns the schema in every environment; tests call
                # Base.metadata.create_all explicitly, and the cold-start
                # helper init_db() remains opt-in.
                logger.info(
                    "db_engine_initialized",
                    extra={"url": make_url(url).render_as_string(hide_password=True)},
                )
    return _engine


def get_async_engine() -> Any:
    """Get the async SQLAlchemy engine. Lazily creates one on first call."""
    global _async_engine, _async_session_local
    if not _HAS_SA:
        raise RuntimeError("sqlalchemy is not installed; pip install 'sqlalchemy>=2.0'")
    if _async_engine is None:
        with _engine_lock:
            if _async_engine is None:
                url = _resolve_async_database_url()
                _async_engine = create_async_engine(url, echo=False, **_connect_kwargs(url))
                if url.startswith("sqlite"):
                    event.listens_for(_async_engine.sync_engine, "connect")(_enable_sqlite_fk)
                _async_session_local = async_sessionmaker(
                    bind=_async_engine, autoflush=False, expire_on_commit=False
                )
                logger.info(
                    "db_async_engine_initialized",
                    extra={"url": make_url(url).render_as_string(hide_password=True)},
                )
    return _async_engine


def dispose_engines() -> None:
    """Dispose both engine pools (graceful shutdown); idempotent."""
    global _engine, _SessionLocal, _async_engine, _async_session_local
    if _engine is not None:
        with suppress(Exception):
            _engine.dispose()
    if _async_engine is not None:
        with suppress(Exception):
            asyncio.run(_async_engine.dispose())
    _engine = None
    _SessionLocal = None
    _async_engine = None
    _async_session_local = None
