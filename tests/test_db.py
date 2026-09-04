"""Tests for the db module (SQLAlchemy foundation).

Uses a temp directory for PRY_DATA_DIR so we don't pollute the user's
real data dir. Tests verify schema creation, basic CRUD, and the
JSON store importer.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib
import json
import os

import pytest

import pry.core.paths as paths


@pytest.fixture
def temp_data_dir(monkeypatch, tmp_path):
    """Set PRY_DATA_DIR to a temp dir and reload db to pick up the change."""
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    # Force re-import of paths and db
    import pry.core.db as db

    importlib.reload(paths)
    importlib.reload(db)
    # Reset the cached engine
    db._engine = None
    db._SessionLocal = None
    # Create tables explicitly (moved from get_engine to lifespan startup)
    from pry.core.db.session import init_db

    init_db()
    yield tmp_path
    # Cleanup
    db._engine = None
    db._SessionLocal = None


def test_get_engine_creates_db_file(temp_data_dir):
    import pry.core.db as db

    eng = db.get_engine()
    assert eng is not None
    # The DB file should exist now
    assert (temp_data_dir / "test.db").exists()


def test_all_tables_created(temp_data_dir):
    from sqlalchemy import inspect

    import pry.core.db as db

    db.get_engine()
    inspector = inspect(db.get_engine())
    tables = inspector.get_table_names()
    # Should have the 15 live model tables (11 dead models dropped in 0002)
    expected_tables = {
        "quality_checks",
        "intel_snapshots",
        "structure_snapshots",
        "monitors",
        "monitor_runs",
        "accounts",
        "browser_sessions",
        "reports",
        "pipelines",
        "agencies",
        "referral_clicks",
        "referral_conversions",
        "referral_in_app_usage",
        "actors",
        "webhooks",
    }
    assert expected_tables.issubset(set(tables)), f"missing: {expected_tables - set(tables)}"


def test_session_scope_commits_on_success(temp_data_dir):
    import pry.core.db as db

    with db.session_scope() as s:
        s.add(
            db.QualityCheck(
                extraction_id="test-1",
                url="https://example.com",
                completeness=0.9,
            )
        )
    # Verify it was committed
    with db.session_scope() as s:
        from sqlalchemy import select

        result = s.execute(select(db.QualityCheck).where(db.QualityCheck.extraction_id == "test-1"))
        row = result.scalar_one_or_none()
        assert row is not None
        assert row.url == "https://example.com"
        assert row.completeness == 0.9


def test_session_scope_rolls_back_on_error(temp_data_dir):
    import pry.core.db as db

    try:
        with db.session_scope() as s:
            s.add(
                db.QualityCheck(extraction_id="test-2", url="https://example.com", completeness=0.5)
            )
            raise ValueError("intentional")
    except ValueError:
        pass
    # Verify it was NOT committed
    with db.session_scope() as s:
        from sqlalchemy import select

        result = s.execute(select(db.QualityCheck).where(db.QualityCheck.extraction_id == "test-2"))
        assert result.scalar_one_or_none() is None


def test_import_json_stores_reads_existing_data(temp_data_dir):
    """The importer should read existing JSON files and write to SQL tables."""
    # Set up some JSON files
    intel_dir = temp_data_dir / "intel"
    intel_dir.mkdir(parents=True, exist_ok=True)
    (intel_dir / "snapshots.jsonl").write_text(  # use the canonical filename
        json.dumps(
            {
                "competitor_id": "acme",
                "competitor_name": "Acme Corp",
                "url": "https://acme.com",
                "fields": {"price": 99.99},
            }
        )
        + "\n"
        + json.dumps(
            {
                "competitor_id": "acme",
                "competitor_name": "Acme Corp",
                "url": "https://acme.com/pricing",
                "fields": {"price": 89.99},
            }
        )
        + "\n"
    )

    monitor_dir = temp_data_dir / "monitors"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    (monitor_dir / "m1.json").write_text(
        json.dumps(
            {
                "monitor_id": "m1",
                "url": "https://example.com",
                "name": "Example Monitor",
                "schedule_cron": "0 * * * *",
                "active": True,
            }
        )
    )

    import pry.core.db as db

    counts = db.import_json_stores(data_dir=temp_data_dir)
    assert counts.get("intel") == 2
    assert counts.get("monitors") == 1
    assert counts.get("actors") == 0  # empty dir

    # Verify in SQL
    with db.session_scope() as s:
        from sqlalchemy import select

        intel_rows = (
            s.execute(select(db.IntelSnapshot).where(db.IntelSnapshot.competitor_id == "acme"))
            .scalars()
            .all()
        )
        assert len(intel_rows) == 2
        monitor_row = s.execute(
            select(db.Monitor).where(db.Monitor.monitor_id == "m1")
        ).scalar_one_or_none()
        assert monitor_row is not None
        # 'name' from JSON was renamed to 'monitor_name' in SQL
        assert monitor_row.monitor_name == "Example Monitor"


def test_db_health_returns_dict(temp_data_dir):
    import pry.core.db as db

    health = db.db_health()
    assert isinstance(health, dict)
    assert "available" in health
    assert health["available"] is True
    assert "url" in health


def test_alembic_migration_current_works(temp_data_dir, monkeypatch):
    """Verify alembic.current can run against a temp SQLite DB without error."""
    import importlib
    import subprocess
    import sys

    import pry.core.db as db

    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{temp_data_dir}/migration-test.db")
    importlib.reload(db)
    db._engine = None
    db._SessionLocal = None

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "--config", "alembic.ini", "current"],
        capture_output=True,
        text=True,
        env={**os.environ, "PRY_DATABASE_URL": f"sqlite:///{temp_data_dir}/migration-test.db"},
    )
    assert result.returncode == 0, f"alembic current failed (stderr): {result.stderr}"


def test_alembic_migration_upgrade_head_creates_tables(temp_data_dir, monkeypatch):
    """Verify alembic upgrade head creates all expected tables."""
    import importlib
    import subprocess
    import sys

    from sqlalchemy import inspect

    import pry.core.db as db

    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{temp_data_dir}/migration-test.db")
    importlib.reload(db)
    db._engine = None
    db._SessionLocal = None

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "--config", "alembic.ini", "upgrade", "head"],
        capture_output=True,
        text=True,
        env={**os.environ, "PRY_DATABASE_URL": f"sqlite:///{temp_data_dir}/migration-test.db"},
    )
    assert result.returncode == 0, f"alembic upgrade failed: {result.stderr}"

    eng = db.get_engine()
    inspector = inspect(eng)
    tables = inspector.get_table_names()
    # 15 live tables after 0002 drops the 11 dead ones
    expected_tables = {
        "quality_checks",
        "intel_snapshots",
        "structure_snapshots",
        "monitors",
        "monitor_runs",
        "accounts",
        "browser_sessions",
        "reports",
        "pipelines",
        "agencies",
        "referral_clicks",
        "referral_conversions",
        "referral_in_app_usage",
        "actors",
        "webhooks",
    }
    missing = expected_tables - set(tables)
    assert not missing, f"Tables missing after migration: {missing}"


def test_models_have_unique_constraints(temp_data_dir):
    """Tables that map to JSON stores with _id fields should have unique indexes
    so that re-importing the same data is idempotent (or at least detectable)."""
    from sqlalchemy import inspect

    import pry.core.db as db

    db.get_engine()
    inspector = inspect(db.get_engine())
    # monitor_id should be unique in monitors
    monitors_idx = inspector.get_indexes("monitors")
    assert any("monitor_id" in i.get("column_names", []) and i.get("unique") for i in monitors_idx)
    # Same for actors.actor_id
    actors_idx = inspector.get_indexes("actors")
    assert any("actor_id" in i.get("column_names", []) and i.get("unique") for i in actors_idx)


# ---------------------------------------------------------------------------
# Environment-profile database resolution (audit win #18)
# ---------------------------------------------------------------------------


class TestDatabaseProfileResolution:
    """PRY_ENVIRONMENT drives the default backend; explicit URL always wins."""

    def _resolve(self, monkeypatch: pytest.MonkeyPatch) -> str:
        from pry.core.db.session import _resolve_database_url

        return _resolve_database_url()

    def test_dev_defaults_to_sqlite(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PRY_DATABASE_URL", raising=False)
        monkeypatch.setenv("PRY_ENVIRONMENT", "dev")
        assert self._resolve(monkeypatch).startswith("sqlite:///")

    def test_missing_profile_defaults_to_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PRY_DATABASE_URL", raising=False)
        monkeypatch.delenv("PRY_ENVIRONMENT", raising=False)
        assert self._resolve(monkeypatch).startswith("sqlite:///")

    @pytest.mark.parametrize("profile", ["prod", "production", "staging"])
    def test_prod_staging_default_postgres(
        self, monkeypatch: pytest.MonkeyPatch, profile: str
    ) -> None:
        monkeypatch.delenv("PRY_DATABASE_URL", raising=False)
        monkeypatch.setenv("PRY_ENVIRONMENT", profile)
        monkeypatch.delenv("PRY_ALLOW_SQLITE_PROD", raising=False)
        assert self._resolve(monkeypatch).startswith("postgresql://")

    def test_explicit_url_beats_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PRY_DATABASE_URL", "postgresql://x:y@db.example:5432/z")
        monkeypatch.setenv("PRY_ENVIRONMENT", "prod")
        assert self._resolve(monkeypatch) == "postgresql://x:y@db.example:5432/z"

    def test_sqlite_escape_hatch_in_prod_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        monkeypatch.delenv("PRY_DATABASE_URL", raising=False)
        monkeypatch.setenv("PRY_ENVIRONMENT", "prod")
        monkeypatch.setenv("PRY_ALLOW_SQLITE_PROD", "1")
        with caplog.at_level(logging.WARNING, logger="db.session"):
            url = self._resolve(monkeypatch)
        assert url.startswith("sqlite:///")
        assert any(r.message == "sqlite_in_production_allowed" for r in caplog.records)

    def test_async_resolution_converts_postgres_driver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pry.core.db.session import _resolve_async_database_url

        monkeypatch.delenv("PRY_DATABASE_URL", raising=False)
        monkeypatch.setenv("PRY_ENVIRONMENT", "prod")
        monkeypatch.delenv("PRY_ALLOW_SQLITE_PROD", raising=False)
        assert _resolve_async_database_url().startswith("postgresql+asyncpg://")
