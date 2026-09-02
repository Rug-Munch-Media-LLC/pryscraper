# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hosting invoices persist to the DB (revenue records survive restarts).

Audit item #1: the in-memory _INVOICES registry was lost on every container
restart — the revenue records were ephemeral. These tests prove the
signup → invoice → confirm flow writes through to the hosting_invoices
table and reads back after an engine restart (new-process simulation).
"""

from __future__ import annotations

from typing import Any

import pytest

import pry.commerce.hosting as hosting_mod
from pry.commerce.hosting import (
    confirm_hosting_payment_sync,
    create_hosting_signup,
    get_hosting_invoice,
)
from pry.payments.x402.self_facilitator import VerifyResult

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"


class _FakeFacilitator:
    def __init__(self, result: VerifyResult) -> None:
        self.result = result

    async def verify(self, payment: dict[str, Any]) -> VerifyResult:
        return self.result

    async def settle(self, payment: dict[str, Any]) -> str | None:
        return "0x" + "f" * 64


def _verified_result() -> VerifyResult:
    return VerifyResult(
        verified=True,
        reason="",
        signer="0xRecoveredSigner0000000000000000000000000000",
        amount_atomic=49_000_000,
        asset="USDC",
        network="eip155:8453",
    )


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test (same pattern as test_hosting.py)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/persistence.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)

    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/persistence.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _wallet(monkeypatch):
    monkeypatch.setattr(hosting_mod, "X402_NETWORK_WALLETS", {"eip155:8453": _REAL_WALLET})
    monkeypatch.setattr(hosting_mod, "X402_WALLET", _REAL_WALLET)


def test_create_signup_invoice_writes_to_db(db) -> None:
    invoice = create_hosting_signup("buyer@example.com", "pro")
    from pry.core.db.models import HostingInvoice
    from pry.core.db.session import get_session

    with get_session() as session:
        row = session.query(HostingInvoice).filter_by(invoice_id=invoice["invoice_id"]).first()
    assert row is not None
    assert row.plan_tier == "pro"
    assert row.user_email == "buyer@example.com"
    assert row.status == "pending"
    assert float(row.amount_usd) == 49.0


def test_get_hosting_invoice_reads_from_db(db) -> None:
    created = create_hosting_signup("reader@example.com", "team")
    fetched = get_hosting_invoice(created["invoice_id"])
    assert fetched["invoice_id"] == created["invoice_id"]
    assert fetched["plan_tier"] == "team"
    assert fetched["payment"]["tx_hash"] is None
    with pytest.raises(ValueError, match="unknown hosting invoice"):
        get_hosting_invoice("host_doesnotexist")


def test_confirm_flow_marks_invoice_paid(db, monkeypatch) -> None:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = create_hosting_signup("paid@example.com", "pro")
    result = confirm_hosting_payment_sync(invoice["invoice_id"], "0x" + "a" * 8)
    assert result["paid"] is True

    stored = get_hosting_invoice(invoice["invoice_id"])
    assert stored["status"] == "paid"
    assert stored["credited_reference"].startswith("hosting:")
    assert stored["instance_id"] == result["instance"]["instance_id"]


def test_invoice_survives_restart(db) -> None:
    """Simulate a process restart: dispose engines, read the row back."""
    invoice = create_hosting_signup("restart@example.com", "pro")
    invoice_id = invoice["invoice_id"]

    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    session_mod.dispose_engines()
    db_pkg._engine = None  # force a fresh engine, like a new process

    fetched = get_hosting_invoice(invoice_id)
    assert fetched["invoice_id"] == invoice_id
    assert fetched["plan_tier"] == "pro"
    assert fetched["status"] == "pending"
