"""Pry - Alembic migration runner and database health helpers.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

with suppress(ImportError):  # pragma: no cover
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError, SQLAlchemyError

from pry.core.db.baseline import _already_exists, _stamp_head_after_existing_schema
from pry.core.db.models import _HAS_SA
from pry.core.db.session import (
    _resolve_async_database_url,
    _resolve_database_url,
    get_async_engine,
    get_engine,
)

logger = logging.getLogger(__name__)

# Alembic's own bookkeeping table. Its absence, or an empty version row, is
# how we detect a schema that create_all() made but alembic never stamped.
ALEMBIC_VERSION_TABLE = "alembic_version"

# "already exists" in each backend's wording, matched case-insensitively.
_ALREADY_EXISTS_MARKERS = (
    "already exists",
    "duplicate table",
    "duplicate key value",
)


def run_migrations() -> None:
    """Run pending Alembic migrations (``alembic upgrade head``).

    Optional helper for programmatic migration execution.  Falls back to
    the config file at *alembic.ini* (must be on the sys.path or in CWD).
    Requires the ``alembic`` package (included in ``pry[dev]``).

    Idempotent against a ``create_all``-made schema: a collision on an
    already-existing table is adopted by stamping head, but ONLY when every
    table head would create is present. A partial schema still raises.
    """
    try:
        from alembic.config import Config

        from alembic import command
    except ImportError:
        logger.warning("alembic_not_installed", extra={"hint": "pip install alembic"})
        return
    try:
        cfg = Config("alembic.ini")
        # Force a SYNC driver (see alembic/env.py _to_sync_url) — asyncpg URLs
        # crash the synchronous migration runner with MissingGreenlet.
        cfg.set_main_option(
            "sqlalchemy.url",
            _resolve_database_url()
            .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
            .replace("sqlite+aiosqlite://", "sqlite"),
        )
        command.upgrade(cfg, "head")
        logger.info("migrations_completed")
    except DBAPIError as exc:
        if not _already_exists(exc):
            logger.exception("migrations_failed")
            raise
        if _stamp_head_after_existing_schema():
            logger.info("migrations_adopted_existing_schema")
            return
        logger.exception("migrations_failed")
        raise
    except Exception:
        logger.exception("migrations_failed")
        raise


def _sqlite_version(conn: Any) -> str | None:
    """Return the connected backend's SQLite version, or None if not SQLite.

    ``SELECT 1`` runs first: it is a real round trip, so it distinguishes a
    healthy non-SQLite backend (the driver rejects ``sqlite_version()`` with
    "no such function" but answers ``SELECT 1``) from a dead or unusable
    connection. Only the former degrades to None; anything else propagates so
    a broken database is never reported as available.
    """
    try:
        conn.exec_driver_sql("SELECT 1").fetchone()
    except (OperationalError, ProgrammingError) as e:
        # Round trip failed: the connection is not usable.
        logger.warning(
            "db_health_connectivity_probe_failed", extra={"error_type": type(e).__name__}
        )
        raise

    try:
        result = conn.exec_driver_sql("SELECT sqlite_version()").fetchone()
    except (OperationalError, ProgrammingError) as e:
        # Expected on a *healthy* non-SQLite backend — verified by SELECT 1 above.
        logger.debug(
            "db_health_sqlite_probe_not_applicable", extra={"error_type": type(e).__name__}
        )
        return None
    return result[0] if result else None


def db_health() -> dict[str, Any]:
    """Return a quick health dict for /health or /status endpoints.

    ``available: True`` means the engine actually connected. A connection or
    probe failure returns ``available: False`` with the error, so an unhealthy
    database is never reported as healthy.
    """
    if not _HAS_SA:
        return {"available": False, "reason": "sqlalchemy not installed"}
    try:
        eng = get_engine()
        with eng.connect() as conn:
            # SQLite-specific pragma; None for other backends.
            sqlite_version = _sqlite_version(conn)
        return {
            "available": True,
            "url": _resolve_database_url().split("@")[-1]
            if "@" in _resolve_database_url()
            else _resolve_database_url(),
            "sqlite_version": sqlite_version,
        }
    except SQLAlchemyError as e:
        return {"available": False, "error": str(e)[:200]}


async def db_health_async() -> dict[str, Any]:
    """Async health check for the database (for async endpoints)."""
    if not _HAS_SA:
        return {"available": False, "reason": "sqlalchemy not installed"}
    try:
        engine = get_async_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {
            "available": True,
            "url": _resolve_async_database_url().split("@")[-1]
            if "@" in _resolve_async_database_url()
            else _resolve_async_database_url(),
        }
    except SQLAlchemyError as e:
        return {"available": False, "error": str(e)[:200]}
