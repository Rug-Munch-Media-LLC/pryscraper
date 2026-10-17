# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for bulk scrape-credit packs (x402 crypto checkout + ledger settle).

Covers:
- pack purchase credits the balance (verified x402 payment → deposit credit)
- underpayment is rejected (unverified tx → never credited, never a key)
- balance drawdown is atomic (insufficient balance never goes negative)
- the fail-closed wallet rule (no placeholder payTo is ever emitted)
"""

from __future__ import annotations

import pytest

from pry.commerce import billing_service
from pry.commerce.billing import (
    PackWalletUnconfigured,
    Underpayment,
    confirm_pack_purchase,
    create_pack_invoice,
    list_packs,
    packs,
    reset_pack_state,
)
from pry.payments.x402.self_facilitator import VerifyResult

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"


class _FakeFacilitator:
    """Scripted SelfFacilitator double for pack payment verify + settle."""

    def __init__(self, result: VerifyResult, *, settle_tx: str | None = "0x" + "f" * 64) -> None:
        self.result = result
        self.settle_tx = settle_tx
        self.verified_payments: list[dict] = []
        self.settled_payments: list[dict] = []

    async def verify(self, payment: dict) -> VerifyResult:
        self.verified_payments.append(payment)
        return self.result

    async def settle(self, payment: dict) -> str | None:
        self.settled_payments.append(payment)
        return self.settle_tx


def _verified_result() -> VerifyResult:
    return VerifyResult(
        verified=True,
        reason="",
        signer="0xRecoveredSigner0000000000000000000000000000",
        amount_atomic=5_000_000,
        asset="USDC",
        network="eip155:8453",
    )


def _unverified_result() -> VerifyResult:
    return VerifyResult(
        verified=False,
        reason="authorization amount below price",
        signer="",
        amount_atomic=100_000,
        asset="USDC",
        network="eip155:8453",
    )


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB for the ledger (same pattern as test_api_keys_billing)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)

    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_pack_state(monkeypatch):
    """Reset the in-memory pack invoice registry + wire a real wallet so the
    fail-closed gate passes for the happy-path tests."""
    reset_pack_state()
    monkeypatch.setattr(packs, "X402_NETWORK_WALLETS", {"eip155:8453": _REAL_WALLET})
    monkeypatch.setattr(packs, "X402_WALLET", _REAL_WALLET)
    yield
    reset_pack_state()


# ── Catalog ─────────────────────────────────────────────────────────────────
def test_list_packs_server_authoritative() -> None:
    packs_list = {p["id"]: p for p in list_packs()}
    expected = {"starter", "growth", "bulk"}
    assert set(packs_list) == expected
    starter = packs_list["starter"]
    assert starter["price_usd"] == 5.0
    assert starter["credits"] == 5000
    assert starter["amount_atomic"] == 5_000_000  # 5 USDC, 6 dp
    assert starter["credits_usd"] == 5.0


def test_unknown_pack_raises() -> None:
    with pytest.raises(packs.PackNotFound):
        create_pack_invoice("nonexistent")


# ── Fail-closed wallet rule ────────────────────────────────────────────────
def test_create_invoice_fails_closed_without_wallet(monkeypatch) -> None:
    monkeypatch.setattr(packs, "X402_NETWORK_WALLETS", {"eip155:8453": ""})
    monkeypatch.setattr(packs, "X402_WALLET", "")
    with pytest.raises(PackWalletUnconfigured):
        create_pack_invoice("starter", user_id="u_wallet")
    # Never a placeholder: an unconfigured wallet must not yield a manifest.


def test_create_invoice_emits_real_payto() -> None:
    invoice = create_pack_invoice("starter", user_id="u_payto")
    assert invoice["pay_to"] == _REAL_WALLET
    assert invoice["payment_required"]["accepts"][0]["payToAddress"] == _REAL_WALLET
    assert invoice["amount_atomic"] == 5_000_000
    assert invoice["invoice_id"].startswith("pack_")
    assert invoice["pack_id"] == "starter"


# ── Pack purchase credits the ledger ───────────────────────────────────────
def test_pack_purchase_credits_balance(db, monkeypatch) -> None:
    monkeypatch.setattr(
        packs, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = create_pack_invoice("starter", user_id="u_pack")
    result = confirm_pack_purchase(invoice["invoice_id"], "0xdeadbeef", user_id="u_pack")

    assert result["paid"] is True
    assert result["credits"] == 5000
    assert result["amount_usd"] == 5.0
    assert result["api_key"]  # crypto signup: key minted on first purchase

    balance = billing_service.get_balance("u_pack")
    assert balance["balance_usd"] == 5.0

    entries = billing_service.ledger("u_pack")
    deposit = entries[0]
    assert deposit["reason"] == "deposit"
    assert deposit["reference"].startswith("pack:")
    assert deposit["balance_after"] == 5.0


def test_pack_purchase_to_existing_key_owner(db, monkeypatch) -> None:
    """Credits the owner of an existing API key (no duplicate key minted)."""
    from pry.core.api_keys_service import issue_key

    monkeypatch.setattr(
        packs, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    key = issue_key(user_id="u_owner", tier="FREE")
    invoice = create_pack_invoice("growth", user_id="u_owner")
    result = confirm_pack_purchase(
        invoice["invoice_id"],
        "0xabbacafe",
        user_id="u_owner",
        api_key=key["plaintext"],
        mint_key=False,
    )
    assert result["paid"] is True
    assert result["api_key"] == key["plaintext"]  # existing key reused, not re-minted
    assert billing_service.get_balance("u_owner")["balance_usd"] == 20.0


# ── Underpayment is rejected (never credited) ──────────────────────────────
def test_underpayment_rejected(db, monkeypatch) -> None:
    monkeypatch.setattr(
        packs, "_get_self_facilitator", lambda: _FakeFacilitator(_unverified_result())
    )
    invoice = create_pack_invoice("starter", user_id="u_under")
    with pytest.raises(Underpayment):
        confirm_pack_purchase(invoice["invoice_id"], "0xunderpay", user_id="u_under")

    # No credit, no key, balance stays zero.
    assert billing_service.get_balance("u_under")["balance_usd"] == 0.0
    assert billing_service.ledger("u_under") == []


def test_no_payment_reported_is_never_credited(db) -> None:
    invoice = create_pack_invoice("starter", user_id="u_nopay")
    # No tx reported yet: confirm is not reached; verify alone reports unpaid.
    status = packs.verify_pack_payment(invoice["invoice_id"])
    assert status["paid"] is False
    assert "no payment reported" in status["reason"]
    assert billing_service.get_balance("u_nopay")["balance_usd"] == 0.0


# ── Balance drawdown is atomic ─────────────────────────────────────────────
def test_balance_drawdown_atomic(db, monkeypatch) -> None:
    """Funded draws down exactly; an overdraw leaves balance unchanged."""
    monkeypatch.setattr(
        packs, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = create_pack_invoice("starter", user_id="u_atomic")
    confirm_pack_purchase(invoice["invoice_id"], "0xa70mic", user_id="u_atomic")

    after = billing_service.drawdown("u_atomic", 2.0, reference="op:scrape")
    assert after["balance_usd"] == 3.0

    with pytest.raises(billing_service.InsufficientBalance):
        billing_service.drawdown("u_atomic", 99.0, reference="op:huge")
    # Atomic: a rejected overdraw must not touch the balance.
    assert billing_service.get_balance("u_atomic")["balance_usd"] == 3.0


def test_credit_is_idempotent_per_tx(db, monkeypatch) -> None:
    """Re-confirming the same tx does not double-credit the ledger."""
    monkeypatch.setattr(
        packs, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = create_pack_invoice("starter", user_id="u_idem")
    confirm_pack_purchase(invoice["invoice_id"], "0xiddd", user_id="u_idem")
    assert billing_service.get_balance("u_idem")["balance_usd"] == 5.0
    # Re-confirm the identical tx -> no additional credit.
    second = confirm_pack_purchase(
        invoice["invoice_id"], "0xiddd", user_id="u_idem", mint_key=False
    )
    assert second["paid"] is True
    assert billing_service.get_balance("u_idem")["balance_usd"] == 5.0
    deposits = [e for e in billing_service.ledger("u_idem") if e["reason"] == "deposit"]
    assert len(deposits) == 1


# ── Settlement gate: credits ONLY after on-chain settle succeeds ───────────
def test_settle_success_credits_balance(db, monkeypatch) -> None:
    """Verify + settle success -> the ledger is credited and settle was called."""
    fake = _FakeFacilitator(_verified_result())
    monkeypatch.setattr(packs, "_get_self_facilitator", lambda: fake)
    invoice = create_pack_invoice("starter", user_id="u_settle_ok")
    result = confirm_pack_purchase(invoice["invoice_id"], "0xsettled", user_id="u_settle_ok")

    assert result["paid"] is True
    assert result["credits"] == 5000
    # The facilitator's settle was actually invoked with the payment payload.
    assert len(fake.settled_payments) == 1
    assert fake.settled_payments[0]["payment_id"] == invoice["invoice_id"]
    assert billing_service.get_balance("u_settle_ok")["balance_usd"] == 5.0


def test_settle_failure_never_credits(db, monkeypatch) -> None:
    """A failed on-chain settlement must NOT credit — payment-failed response."""
    fake = _FakeFacilitator(_verified_result(), settle_tx=None)
    monkeypatch.setattr(packs, "_get_self_facilitator", lambda: fake)
    invoice = create_pack_invoice("starter", user_id="u_settle_fail")
    result = confirm_pack_purchase(invoice["invoice_id"], "0xnosettle", user_id="u_settle_fail")

    assert result["paid"] is False
    assert result["credits"] == 0
    assert "settlement" in result["reason"]
    assert len(fake.settled_payments) == 1  # settle was attempted

    # No credit, no ledger entry, no key minted.
    assert billing_service.get_balance("u_settle_fail")["balance_usd"] == 0.0
    assert billing_service.ledger("u_settle_fail") == []
