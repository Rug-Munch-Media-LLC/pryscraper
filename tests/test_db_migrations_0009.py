"""Migration 0009 — x402 attribution, ledger uniqueness, hosting tables.

Runs the real Alembic chain against a temp SQLite DB (the ``temp_data_dir``
fixture) and asserts the four defects 0009 fixes stay fixed:

* ``user_id`` on both x402 ledger tables,
* ``hosting_plans`` / ``hosted_instances`` exist with the model's columns,
* duplicate ``(payment_id, tx_hash)`` inserts are rejected,
* the revision round-trips down to 0008 and back.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

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


def _alembic_config(url: str):
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _columns(engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def _indexes(engine, table: str) -> dict[str, dict]:
    return {index["name"]: index for index in inspect(engine).get_indexes(table)}


@pytest.fixture
def migrated(temp_data_dir, monkeypatch):
    """Apply the full chain to a temp SQLite DB and hand back its engine."""
    import pry.core.db as db

    monkeypatch.chdir(REPO_ROOT)
    db.run_migrations()
    return db.get_engine()


def test_0009_tables_and_columns(migrated):
    tables = set(inspect(migrated).get_table_names())
    assert {"hosting_plans", "hosted_instances"} <= tables
    assert "user_id" in _columns(migrated, PAYMENT)
    assert "user_id" in _columns(migrated, SETTLEMENT)
    assert "payment_id" in _columns(migrated, USAGE)


def test_0009_unique_index_is_composite(migrated):
    unique = _indexes(migrated, PAYMENT)[UX_PAYMENT_TX]
    assert unique["unique"] == 1
    assert unique["column_names"] == ["payment_id", "tx_hash"]


def test_0009_hosting_schema_matches_models(migrated):
    assert _columns(migrated, "hosting_plans") == PLAN_COLUMNS
    assert _columns(migrated, "hosted_instances") == INSTANCE_COLUMNS
    fks = inspect(migrated).get_foreign_keys("hosted_instances")
    assert len(fks) == 1
    assert fks[0]["constrained_columns"] == ["user_id"]
    assert fks[0]["referred_table"] == "users"
    assert fks[0]["referred_columns"] == ["user_id"]


def test_0009_duplicate_payment_tx_rejected(migrated):
    insert = text(
        "INSERT INTO x402_payment_records (payment_id, tx_hash, created_at) "
        "VALUES (:payment_id, :tx_hash, CURRENT_TIMESTAMP)"
    )

    with migrated.begin() as conn:
        conn.execute(insert, {"payment_id": "pay_1", "tx_hash": "0xabc"})

    with pytest.raises(IntegrityError), migrated.begin() as conn:
        conn.execute(insert, {"payment_id": "pay_1", "tx_hash": "0xabc"})

    # The constraint is composite: a new payment_id reusing the tx_hash is a
    # different ledger event and must still be accepted.
    with migrated.begin() as conn:
        conn.execute(insert, {"payment_id": "pay_2", "tx_hash": "0xabc"})


def test_0009_downgrade_upgrade_round_trip(migrated):
    from alembic import command

    cfg = _alembic_config(migrated.url.render_as_string(hide_password=False))

    command.downgrade(cfg, "0008")
    tables = set(inspect(migrated).get_table_names())
    assert "hosting_plans" not in tables
    assert "hosted_instances" not in tables
    assert "user_id" not in _columns(migrated, PAYMENT)
    assert "user_id" not in _columns(migrated, SETTLEMENT)
    assert "payment_id" not in _columns(migrated, USAGE)

    command.upgrade(cfg, "head")
    tables = set(inspect(migrated).get_table_names())
    assert {"hosting_plans", "hosted_instances"} <= tables
    assert "user_id" in _columns(migrated, PAYMENT)
    assert UX_PAYMENT_TX in _indexes(migrated, PAYMENT)


def test_0009_backfills_and_dedupes_before_unique_index(temp_data_dir, monkeypatch):
    """Rows written at 0008 must not make the unique index creation fail.

    Reproduces the production shape: duplicate (payment_id, tx_hash) rows and
    NULL tx_hash values. 0009 must collapse the duplicates, normalise NULLs to
    '', and only then build UNIQUE(payment_id, tx_hash).
    """
    import pry.core.db as db
    from alembic import command

    monkeypatch.chdir(REPO_ROOT)
    # Authentic pre-0009 state: no model auto-create masking the migration.
    monkeypatch.setenv("PRY_ALEMBIC_AUTO", "0")
    cfg = _alembic_config(f"sqlite:///{temp_data_dir}/test.db")
    command.upgrade(cfg, "0008")

    engine = db.get_engine()
    insert = text(
        "INSERT INTO x402_payment_records (payment_id, tx_hash, created_at) "
        "VALUES (:payment_id, :tx_hash, CURRENT_TIMESTAMP)"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"payment_id": "p", "tx_hash": None})
        conn.execute(insert, {"payment_id": "p", "tx_hash": None})
        conn.execute(insert, {"payment_id": "p", "tx_hash": "0x1"})
        conn.execute(insert, {"payment_id": "p", "tx_hash": "0x1"})
        conn.execute(insert, {"payment_id": "q", "tx_hash": ""})

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT payment_id, tx_hash, COUNT(*) FROM x402_payment_records "
                "GROUP BY payment_id, tx_hash ORDER BY payment_id, tx_hash"
            )
        ).all()
    assert rows == [("p", "", 1), ("p", "0x1", 1), ("q", "", 1)]


def test_0009_tolerates_hosting_tables_precreated_by_auto_create(temp_data_dir, monkeypatch):
    """A DB the app touched first already has the hosting tables.

    ``get_engine()`` runs ``Base.metadata.create_all`` when PRY_ALEMBIC_AUTO is
    unset (the default). The two hosting models are NEW TABLES, so they appear
    before Alembic reaches 0009 — the revision must not abort on that shape.
    """
    import pry.core.db as db
    from alembic import command

    monkeypatch.chdir(REPO_ROOT)
    cfg = _alembic_config(f"sqlite:///{temp_data_dir}/test.db")
    command.upgrade(cfg, "0008")

    engine = db.get_engine()  # auto-create is ON for this test
    assert "hosting_plans" in set(inspect(engine).get_table_names())

    command.upgrade(cfg, "head")

    tables = set(inspect(engine).get_table_names())
    assert {"hosting_plans", "hosted_instances"} <= tables
    assert "user_id" in _columns(engine, PAYMENT)
