# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""End-to-end integration tests for the hosting revenue door (audit item #12).

signup → pay → confirm (verify + settle) → provision → API key minted.

Real functions throughout (:func:`create_hosting_signup`,
:func:`confirm_hosting_payment_sync`, provisioning, billing ledger, invoice
persistence); only the on-chain self-facilitator is faked via the
``_FakeFacilitator`` double from ``tests/test_hosting.py``.

Covers:
- full signup → pay → provision flow (instance + one-time API key + ledger credit)
- renewal extends the SAME instance (no re-provision, no new key)
- underpayment never provisions and never credits
- settlement failure never provisions and never credits
- double-confirm with the same proof is idempotent (one credit, one instance)
"""

from __future__ import annotations

from typing import Any

import pytest

import pry.commerce.hosting as hosting_mod
from pry.commerce import billing_service
from pry.commerce.hosting import (
    Underpayment,
    confirm_hosting_payment_sync,
    create_hosting_signup,
    get_hosting_invoice,
    renew_instance,
)
from pry.payments.x402.self_facilitator import VerifyResult

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"


class _FakeFacilitator:
    """Scripted SelfFacilitator double (same pattern as tests/test_hosting.py)."""

    def __init__(self, result: VerifyResult, *, settle_tx: str | None = "0x" + "f" * 64) -> None:
        self.result = result
        self.settle_tx = settle_tx
        self.verified_payments: list[dict[str, Any]] = []
        self.settled_payments: list[dict[str, Any]] = []

    async def verify(self, payment: dict[str, Any]) -> VerifyResult:
        self.verified_payments.append(payment)
        return self.result

    async def settle(self, payment: dict[str, Any]) -> str | None:
        self.settled_payments.append(payment)
        return self.settle_tx


def _verified_result() -> VerifyResult:
    return VerifyResult(
        verified=True,
        reason="",
        signer="0xRecoveredSigner0000000000000000000000000000",
        amount_atomic=49_000_000,
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


@pytest.fixture(autouse=True)
def _clean_hosting_state(tmp_path, monkeypatch):
    """Isolated per-test SQLite DB + real treasury wallet (test_hosting.py pattern)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/hosting-int.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)
    hosting_mod.reset_hosting_state()
    monkeypatch.setattr(hosting_mod, "X402_NETWORK_WALLETS", {"eip155:8453": _REAL_WALLET})
    monkeypatch.setattr(hosting_mod, "X402_WALLET", _REAL_WALLET)
    # Test escape hatch: legacy flows confirm without verifying the email
    # first (the email gate itself is covered in test_hosting_email_verification).
    monkeypatch.setenv("PRY_HOSTING_SKIP_EMAIL_VERIFY", "1")
    yield
    hosting_mod.reset_hosting_state()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Engine handle for direct row assertions (same DB as _clean_hosting_state)."""
    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/hosting-int.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _fake_facilitator(
    monkeypatch, result: VerifyResult, *, settle_tx: str | None = "0x" + "f" * 64
) -> _FakeFacilitator:
    fake = _FakeFacilitator(result, settle_tx=settle_tx)
    monkeypatch.setattr(hosting_mod, "_get_self_facilitator", lambda: fake)
    return fake


def _count_instances(user_id: str) -> int:
    from pry.core.db.models import HostedInstance
    from pry.core.db.session import get_session

    with get_session() as session:
        return session.query(HostedInstance).filter_by(user_id=user_id).count()


# ── a. Full revenue door: signup → pay → provision ─────────────────────────
def test_signup_pay_provision_full_flow(db, monkeypatch) -> None:
    _fake_facilitator(monkeypatch, _verified_result())

    invoice = create_hosting_signup("buyer@example.com", "pro")
    assert invoice["amount_usd"] == 49.0
    assert invoice["pay_to"] == _REAL_WALLET

    result = confirm_hosting_payment_sync(invoice["invoice_id"], "0x" + "a" * 8)

    assert result["paid"] is True
    instance = result["instance"]
    assert instance["instance_id"].startswith("inst_")
    assert instance["status"] == "active"
    assert instance["plan_tier"] == "pro"

    # Plaintext API key shown exactly once (never stored on the instance).
    assert isinstance(result["api_key"], str)
    assert result["api_key"].startswith("pry_")
    assert instance["api_key_id"]
    assert instance["api_key_id"] != result["api_key"]

    # Invoice persisted as paid and bound to the provisioned instance.
    stored = get_hosting_invoice(invoice["invoice_id"])
    assert stored["status"] == "paid"
    assert stored["instance_id"] == instance["instance_id"]

    # Billing ledger credited with the plan price under the settle reference.
    entries = billing_service.ledger(instance["user_id"])
    assert len(entries) == 1
    credit = entries[0]
    assert credit["reason"] == "deposit"
    assert credit["reference"] == result["reference"]
    assert credit["reference"].startswith(f"hosting:{invoice['invoice_id']}:")
    assert billing_service.get_balance(instance["user_id"])["balance_usd"] == 49.0


# ── b. Renewal extends, never re-provisions ────────────────────────────────
def test_renewal_extends_and_does_not_reprovision(db, monkeypatch) -> None:
    _fake_facilitator(monkeypatch, _verified_result())

    signup = create_hosting_signup("renew@example.com", "pro")
    first = confirm_hosting_payment_sync(signup["invoice_id"], "0x" + "a" * 8)
    instance_id = first["instance"]["instance_id"]
    user_id = first["instance"]["user_id"]

    renewal = renew_instance(instance_id)
    assert renewal["invoice_id"] != signup["invoice_id"]
    second = confirm_hosting_payment_sync(renewal["invoice_id"], "0x" + "b" * 8)

    assert second["paid"] is True
    # Same instance extended — not a new one.
    assert second["instance"]["instance_id"] == instance_id
    assert second["api_key"] is None  # no new key minted on renewal
    assert _count_instances(user_id) == 1


# ── c. Underpayment never provisions ───────────────────────────────────────
def test_underpayment_never_provisions(db, monkeypatch) -> None:
    _fake_facilitator(monkeypatch, _unverified_result())

    invoice = create_hosting_signup("under@example.com", "pro")
    with pytest.raises(Underpayment):
        confirm_hosting_payment_sync(invoice["invoice_id"], "0xunderpay")

    user_id = invoice["user_id"]
    assert _count_instances(user_id) == 0
    stored = get_hosting_invoice(invoice["invoice_id"])
    assert stored["status"] != "paid"
    assert billing_service.ledger(user_id) == []


# ── d. Settlement failure never provisions ─────────────────────────────────
def test_settlement_failure_never_provisions(db, monkeypatch) -> None:
    _fake_facilitator(monkeypatch, _verified_result(), settle_tx=None)

    invoice = create_hosting_signup("settle@example.com", "pro")
    result = confirm_hosting_payment_sync(invoice["invoice_id"], "0x" + "c" * 8)

    assert result["paid"] is False
    assert result["instance"] is None
    assert result["api_key"] is None
    assert _count_instances(invoice["user_id"]) == 0
    assert billing_service.ledger(invoice["user_id"]) == []
    assert get_hosting_invoice(invoice["invoice_id"])["status"] != "paid"


# ── e. Double confirm is idempotent ────────────────────────────────────────
def test_double_confirm_idempotent(db, monkeypatch) -> None:
    _fake_facilitator(monkeypatch, _verified_result())

    invoice = create_hosting_signup("idem@example.com", "pro")
    proof = "0x" + "d" * 8
    first = confirm_hosting_payment_sync(invoice["invoice_id"], proof)
    assert first["paid"] is True
    reference = first["reference"]
    instance_id = first["instance"]["instance_id"]

    second = confirm_hosting_payment_sync(invoice["invoice_id"], proof)
    assert second["paid"] is True
    assert second["instance"]["instance_id"] == instance_id

    # Exactly one ledger credit under the same settle reference.
    entries = billing_service.ledger(first["instance"]["user_id"])
    assert len(entries) == 1
    assert entries[0]["reference"] == reference
    # Exactly one instance exists.
    assert _count_instances(first["instance"]["user_id"]) == 1
