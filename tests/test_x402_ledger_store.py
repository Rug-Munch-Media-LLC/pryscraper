# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Postgres-backed x402 ledger storage round-trips + DB-enforced idempotency."""

from __future__ import annotations

import pytest

from pry.payments.x402 import ledger_store as store


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/ledger.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)

    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/ledger.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _payment(payment_id: str = "pay_1", **over: object) -> dict:
    rec = {
        "payment_id": payment_id,
        "tx_hash": "0x" + "a" * 64,
        "network": "eip155:8453",
        "asset": "USDC",
        "amount_usd": 0.001,
        "required_amount_atomic": "1000",
        "operation": "scrape",
        "verified": True,
        "verified_at": "2026-09-02T00:00:00+00:00",
        "expires_at": "2026-09-02T01:00:00+00:00",
        "facilitator": "self-hosted",
        "caller_key": "k_abc",
        "reason": "",
    }
    rec.update(over)
    return rec


def test_payment_round_trip_preserves_fields(db) -> None:
    rec = _payment()
    store.record_payment(rec)
    got = store.payments_for("pay_1")
    assert len(got) == 1
    g = got[0]
    assert g["payment_id"] == "pay_1"
    assert g["verified"] is True
    assert g["required_amount_atomic"] == "1000"
    assert g["verified_at"].startswith("2026-09-02")
    assert g["caller_key"] == "k_abc"
    assert g["amount_usd"] == 0.001


def test_record_payment_upsert_by_payment_id_and_tx(db) -> None:
    store.record_payment(_payment())
    store.record_payment(_payment(verified=False, reason="retried"))
    got = store.payments_for("pay_1")
    assert len(got) == 1  # same (payment_id, tx_hash) → updated, not duplicated
    assert got[0]["verified"] is False
    assert got[0]["reason"] == "retried"


def test_settlement_idempotency_db_enforced(db) -> None:
    receipt = {
        "success": True,
        "transaction": "0x" + "b" * 64,
        "tx_hash": "0x" + "a" * 64,
        "network": "eip155:8453",
        "payment_id": "pay_1",
        "asset": "USDC",
        "amount_usd": 0.001,
        "facilitator": "eip-7702",
        "settled_at": "2026-09-02T00:05:00+00:00",
    }
    key = "tx:eip155:8453:" + receipt["tx_hash"]
    first = store.record_settlement(receipt, key)
    assert first["success"] is True
    # Concurrent/duplicate insert → the EXISTING receipt, no second row.
    second = store.record_settlement({**receipt, "settled_at": "9999-01-01"}, key)
    assert second["settled_at"] == first["settled_at"]
    assert store.settlement_by_key(key)["tx_hash"] == receipt["tx_hash"]
    assert len(store.get_settlements()) == 1


def test_settlement_key_collision_fallback_pid(db) -> None:
    """pid:{payment_id} fallback when no tx_hash is present (legacy shape)."""
    receipt = {"payment_id": "legacy_1", "success": True, "facilitator": "stub"}
    got = store.record_settlement(receipt, "pid:legacy_1")
    assert got["payment_id"] == "legacy_1"
    assert store.settlement_by_key("pid:legacy_1")["payment_id"] == "legacy_1"


def test_restart_survival(db) -> None:
    store.record_payment(_payment("survivor"))
    store.record_settlement(
        {"payment_id": "s", "tx_hash": "0x" + "b" * 64, "success": True},
        "tx:eip155:8453:0x" + "b" * 64,
    )
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    session_mod.dispose_engines()
    db_pkg._engine = None

    assert store.payments_for("survivor")[0]["payment_id"] == "survivor"
    assert len(store.get_settlements()) == 1
    assert store.available() is True
