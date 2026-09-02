"""Pry - Alembic migration runner and database health helpers.

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
from contextlib import suppress
from typing import Any

with suppress(ImportError):  # pragma: no cover
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

from pry.core.db.models import _HAS_SA
from pry.core.db.session import (
    _resolve_async_database_url,
    _resolve_database_url,
    get_async_engine,
    get_engine,
)

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Run pending Alembic migrations (``alembic upgrade head``).

    Optional helper for programmatic migration execution.  Falls back to
    the config file at *alembic.ini* (must be on the sys.path or in CWD).
    Requires the ``alembic`` package (included in ``pry[dev]``).
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
    except Exception:
        logger.exception("migrations_failed")
        raise


def db_health() -> dict[str, Any]:
    """Return a quick health dict for /health or /status endpoints."""
    if not _HAS_SA:
        return {"available": False, "reason": "sqlalchemy not installed"}
    try:
        eng = get_engine()
        with eng.connect() as conn:
            # SQLite-specific pragma; no-op for other backends
            try:
                result = conn.exec_driver_sql("SELECT sqlite_version()").fetchone()
                sqlite_version = result[0] if result else None
            except (OperationalError, ProgrammingError):
                sqlite_version = None
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
