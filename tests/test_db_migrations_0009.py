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

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.db_migrations_support import (  # noqa: F401 — fixture for this module
    INSTANCE_COLUMNS,
    PAYMENT,
    PLAN_COLUMNS,
    REPO_ROOT,
    SETTLEMENT,
    USAGE,
    UX_PAYMENT_TX,
    alembic_config,
    columns,
    indexes,
    migrated,
)


def test_0009_tables_and_columns(migrated):
    tables = set(inspect(migrated).get_table_names())
    assert {"hosting_plans", "hosted_instances"} <= tables
    assert "user_id" in columns(migrated, PAYMENT)
    assert "user_id" in columns(migrated, SETTLEMENT)
    assert "payment_id" in columns(migrated, USAGE)


def test_0009_unique_index_is_composite(migrated):
    unique = indexes(migrated, PAYMENT)[UX_PAYMENT_TX]
    assert unique["unique"] == 1
    expected = ["payment_id", "tx_hash"]
    assert unique["column_names"] == expected


def test_0009_hosting_schema_matches_models(migrated):
    assert columns(migrated, "hosting_plans") == PLAN_COLUMNS
    assert columns(migrated, "hosted_instances") == INSTANCE_COLUMNS
    fks = inspect(migrated).get_foreign_keys("hosted_instances")
    assert len(fks) == 1
    expected = ["user_id"]
    assert fks[0]["constrained_columns"] == expected
    assert fks[0]["referred_table"] == "users"
    expected_2 = ["user_id"]
    assert fks[0]["referred_columns"] == expected_2


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


def test_0009_downgrade_upgrade_round_trip(migrated, monkeypatch):
    from alembic import command

    cfg = alembic_config(migrated.url.render_as_string(hide_password=False))
    monkeypatch.setenv("PRY_ALLOW_LOSSY_DOWNGRADE", "1")
    # 0012 guards its own downgrade; the refusal path is covered by
    # test_billing_dunning. This round-trip must reach 0008 to be exercised.
    monkeypatch.setenv("PRY_ALLOW_BILLING_DOWNGRADE", "1")

    command.downgrade(cfg, "0008")
    tables = set(inspect(migrated).get_table_names())
    assert "hosting_plans" not in tables
    assert "hosted_instances" not in tables
    assert "user_id" not in columns(migrated, PAYMENT)
    assert "user_id" not in columns(migrated, SETTLEMENT)
    assert "payment_id" not in columns(migrated, USAGE)

    command.upgrade(cfg, "head")
    tables = set(inspect(migrated).get_table_names())
    assert {"hosting_plans", "hosted_instances"} <= tables
    assert "user_id" in columns(migrated, PAYMENT)
    assert UX_PAYMENT_TX in indexes(migrated, PAYMENT)


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
    # Destructive dedupe is now opt-in and requires a verified dump path.
    monkeypatch.setenv("PRY_ALLOW_X402_DEDUPE", "1")
    dump = temp_data_dir / "dump"
    dump.write_bytes(b"SQLite format 3\x00" + b"x" * 64)  # non-empty verified dump
    monkeypatch.setenv("PRY_X402_BACKUP_PATH", str(dump))
    cfg = alembic_config(f"sqlite:///{temp_data_dir}/test.db")
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
    expected = [("p", "", 1), ("p", "0x1", 1), ("q", "", 1)]
    assert rows == expected


def test_0009_tolerates_hosting_tables_precreated_by_auto_create(temp_data_dir, monkeypatch):
    """A DB the app touched first already has the hosting tables.

    ``get_engine()`` runs ``Base.metadata.create_all`` when PRY_ALEMBIC_AUTO is
    unset (the default). The two hosting models are NEW TABLES, so they appear
    before Alembic reaches 0009 — the revision must not abort on that shape.
    """
    import pry.core.db as db
    from alembic import command

    monkeypatch.chdir(REPO_ROOT)
    cfg = alembic_config(f"sqlite:///{temp_data_dir}/test.db")
    command.upgrade(cfg, "0008")

    engine = db.get_engine()
    # 2026-10-18: get_engine() no longer runs create_all (schema drift P1).
    # Keep the shape under test by creating the tables the old path created.
    from pry.core.db.models import Base

    Base.metadata.create_all(engine)
    assert "hosting_plans" in set(inspect(engine).get_table_names())

    command.upgrade(cfg, "head")

    tables = set(inspect(engine).get_table_names())
    assert {"hosting_plans", "hosted_instances"} <= tables
    assert "user_id" in columns(engine, PAYMENT)
