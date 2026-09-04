"""Tests for ``pry.core.db.migrations`` — Alembic runner + DB health helpers.

Covers ``run_migrations()``, ``db_health()``, and ``db_health_async()`` with
concrete assertions on table creation, health-dict contents, and error
handling. Uses a temp SQLite DB so the user's real data dir is never touched.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

import pry.core.paths as paths

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def temp_data_dir(monkeypatch, tmp_path):
    """Point PRY_DATA_DIR/PRY_DATABASE_URL at a temp dir and reset the engine."""
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import pry.core.db as db

    importlib.reload(paths)
    importlib.reload(db)
    db._engine = None
    db._SessionLocal = None
    yield tmp_path
    db._engine = None
    db._SessionLocal = None


# ── run_migrations ────────────────────────────────────────────────


def test_run_migrations_creates_all_tables(temp_data_dir, monkeypatch):
    """run_migrations() applies every Alembic revision to a fresh DB."""
    from sqlalchemy import inspect

    import pry.core.db as db

    monkeypatch.chdir(REPO_ROOT)
    db.run_migrations()

    inspector = inspect(db.get_engine())
    tables = set(inspector.get_table_names())
    # One table per migration revision, proving each revision ran.
    assert "quality_checks" in tables  # 0001
    assert "monitors" in tables  # 0001
    assert "users" in tables  # 0003
    assert "hosting_invoices" in tables  # 0004
    assert "audit_events" in tables  # 0006
    assert "x402_payment_records" in tables  # 0007
    assert "balances" in tables  # b3b4faf8e50d


def test_run_migrations_is_idempotent(temp_data_dir, monkeypatch):
    """Running migrations twice must not error or change the schema."""
    from sqlalchemy import inspect

    import pry.core.db as db

    monkeypatch.chdir(REPO_ROOT)
    db.run_migrations()
    inspector = inspect(db.get_engine())
    tables_before = set(inspector.get_table_names())

    db.run_migrations()  # second run should be a no-op

    inspector = inspect(db.get_engine())
    tables_after = set(inspector.get_table_names())
    assert tables_after == tables_before


def test_run_migrations_when_alembic_missing_logs_warning(temp_data_dir, monkeypatch, caplog):
    """If alembic is not installed, run_migrations logs a warning and returns None."""
    import logging

    import pry.core.db.migrations as mig

    # Simulate alembic not being installed. Setting the module to None in
    # sys.modules makes `from alembic.config import Config` raise ImportError
    # ("import of alembic halted; None in sys.modules"). We set the top-level
    # package AND the submodule so the import is halted regardless of which is
    # resolved first. (The old loop only nulled modules already present in
    # sys.modules, but alembic is imported lazily inside run_migrations(), so
    # it was never there and the ImportError branch was never exercised.)
    monkeypatch.setitem(sys.modules, "alembic", None)
    monkeypatch.setitem(sys.modules, "alembic.config", None)

    # Ensure the stdlib logger is enabled and propagates to caplog's root
    # handler so the warning is captured. Earlier tests in this file run real
    # Alembic migrations, and alembic/env.py calls logging.config.fileConfig()
    # (disable_existing_loggers=True), which DISABLES every logger not listed
    # in alembic.ini — including this one. Re-enable it and force propagation
    # so the record reaches caplog (structlog's bridge can otherwise swallow
    # it too).
    _mig_logger = logging.getLogger("pry.core.db.migrations")
    _mig_logger.disabled = False
    _mig_logger.propagate = True

    with caplog.at_level(logging.WARNING, logger="pry.core.db.migrations"):
        result = mig.run_migrations()
    assert result is None
    assert any("alembic_not_installed" in r.getMessage() for r in caplog.records)


# ── db_health (sync) ──────────────────────────────────────────────


def test_db_health_available(temp_data_dir):
    """A reachable SQLite DB reports available=True with url + sqlite_version."""
    import pry.core.db as db

    health = db.db_health()
    assert health["available"] is True
    assert health["url"]  # non-empty
    # SQLite backend reports a version string (e.g. "3.x.y").
    assert health["sqlite_version"] is not None


def test_db_health_when_sa_missing(monkeypatch):
    """Without SQLAlchemy, db_health reports unavailable with a reason."""
    import pry.core.db.migrations as mig

    monkeypatch.setattr(mig, "_HAS_SA", False)
    health = mig.db_health()
    assert health["available"] is False
    assert health["reason"] == "sqlalchemy not installed"


def test_db_health_on_sqlalchemy_error(monkeypatch):
    """A failing engine connection reports available=False with an error string."""
    from sqlalchemy.exc import OperationalError

    import pry.core.db.migrations as mig

    def _boom():
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    monkeypatch.setattr(mig, "get_engine", _boom)
    health = mig.db_health()
    assert health["available"] is False
    assert "error" in health
    assert "db down" in health["error"]


# ── db_health_async ──────────────────────────────────────────────


async def test_db_health_async_available(temp_data_dir):
    """The async health probe reports available=True against a reachable DB."""
    import pry.core.db as db

    health = await db.db_health_async()
    assert health["available"] is True
    assert health["url"]  # non-empty


async def test_db_health_async_when_sa_missing(monkeypatch):
    """Without SQLAlchemy, the async probe reports unavailable with a reason."""
    import pry.core.db.migrations as mig

    monkeypatch.setattr(mig, "_HAS_SA", False)
    health = await mig.db_health_async()
    assert health["available"] is False
    assert health["reason"] == "sqlalchemy not installed"
