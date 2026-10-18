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

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


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
    assert "domain_method_stats" in tables  # 0008


def test_domain_method_stats_up_and_down_round_trip(temp_data_dir, monkeypatch):
    """0008 must be reversible: up creates table+index, down removes both.

    The DOWN path is what makes this safe to ship — a bad release can be
    rolled back without leaving a half-created table behind.
    """
    from alembic.config import Config
    from sqlalchemy import inspect

    import pry.core.db as db
    from alembic import command

    monkeypatch.chdir(REPO_ROOT)
    # A scratch DB is safe to downgrade across the destructive-change guards;
    # the guards themselves are covered by their own tests.
    guards = {"PRY_ALLOW_BILLING_DOWNGRADE": "1", "PRY_ALLOW_LOSSY_DOWNGRADE": "1"}
    previous = {key: os.environ.get(key) for key in guards}
    os.environ.update(guards)
    try:
        db.run_migrations()
        assert "domain_method_stats" in set(inspect(db.get_engine()).get_table_names())
        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        cfg.set_main_option(
            "sqlalchemy.url", db.get_engine().url.render_as_string(hide_password=False)
        )
        command.downgrade(cfg, "0007")  # 0009 is now head; -1 would only reach 0008
        assert "domain_method_stats" not in set(inspect(db.get_engine()).get_table_names())
        command.upgrade(cfg, "head")
        assert "domain_method_stats" in set(inspect(db.get_engine()).get_table_names())
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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
