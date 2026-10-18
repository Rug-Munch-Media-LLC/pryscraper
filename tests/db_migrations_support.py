"""Shared constants and helpers for the Alembic migration tests.

Split out of ``test_db_migrations_0009.py`` so the test module stays a single
subject under the 200-line file gate.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect

REPO_ROOT = Path(__file__).resolve().parent.parent

PAYMENT = "x402_payment_records"
SETTLEMENT = "x402_settlement_records"
USAGE = "usage"
UX_PAYMENT_TX = "ux_x402_payment_records_payment_tx"

PLAN_COLUMNS = {
    "tier",
    "name",
    "price_usd_monthly",
    "max_concurrent_scrapes",
    "max_pages_month",
    "storage_gb",
    "features",
    "created_at",
}
INSTANCE_COLUMNS = {
    "id",
    "instance_id",
    "user_id",
    "plan_tier",
    "status",
    "api_key",
    "created_at",
    "expires_at",
    "region",
    "resource_limit",
}


def alembic_config(url: str):
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def columns(engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def indexes(engine, table: str) -> dict[str, dict]:
    return {index["name"]: index for index in inspect(engine).get_indexes(table)}


@pytest.fixture
def migrated(temp_data_dir, monkeypatch):
    """Apply the full chain to a temp SQLite DB and hand back its engine."""
    import pry.core.db as db

    monkeypatch.chdir(REPO_ROOT)
    db.run_migrations()
    return db.get_engine()
