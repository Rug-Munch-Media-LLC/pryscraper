# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for crypto subscription billing (x402 self-facilitator + BTCPay)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from billing import (
    activate_subscription,
    create_subscription_invoice,
    reset_subscription_state,
    set_subscription_store_path,
    submit_subscription_payment,
    subscription_status,
    verify_subscription_payment,
)
from pry.payments.x402.scheme import X402Scheme
from pry.payments.x402.self_facilitator import VerifyResult

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


# ── Test doubles ──────────────────────────────────────────────────────────
class _FakeResponse:
    """Minimal httpx.Response stand-in used when mocking the BTCPay API."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeFacilitator:
    """Fake SelfFacilitator returning a scripted VerifyResult."""

    def __init__(self, result: VerifyResult) -> None:
        self.result = result
        self.verified_payments: list[dict[str, Any]] = []

    async def verify(self, payment: dict[str, Any]) -> VerifyResult:
        self.verified_payments.append(payment)
        return self.result


def _verified_result(signer: str = "0xRecoveredSigner0000000000000000000000000000") -> VerifyResult:
    return VerifyResult(
        verified=True,
        reason="",
        signer=signer,
        amount_atomic=49_000_000,
        asset="USDC",
        network="eip155:8453",
    )


# ── Fixtures ──────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_billing_state(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Reset module registries + env so tests are isolated from each other."""
    import billing.subscription as subs_mod

    subs_mod._INVOICES.clear()
    subs_mod._SUBSCRIPTIONS.clear()
    set_subscription_store_path(None)
    for var in (
        "PRY_BTCPAY_URL",
        "PRY_BTCPAY_API_KEY",
        "PRY_BTCPAY_STORE",
        "PRY_SUBSCRIPTION_INVOICE_TTL",
        "PRY_SUBSCRIPTIONS_FILE",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
    subs_mod._INVOICES.clear()
    subs_mod._SUBSCRIPTIONS.clear()
    set_subscription_store_path(None)


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, value: datetime) -> None:
    import billing.subscription as subs_mod

    monkeypatch.setattr(subs_mod, "_now", lambda: value)


# ── Invoice creation: x402 (default) ──────────────────────────────────────
def test_create_invoice_x402_shape() -> None:
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    assert invoice["payment_method"] == "x402"
    assert invoice["tier"] == "pro"
    assert invoice["amount_usd"] == 49.0
    assert invoice["amount_asset"] == "49000000"  # 49 USDC atomic (6 dp)
    assert invoice["chain"] == "eip155:8453"
    assert invoice["asset"] == "USDC"
    assert invoice["payment_address"]
    assert invoice["invoice_id"].startswith("inv_")


def test_create_invoice_x402_multiple_months() -> None:
    invoice = create_subscription_invoice("team", "sk_team_1", months=2)
    assert invoice["amount_usd"] == 398.0  # 199 * 2
    assert invoice["amount_asset"] == "398000000"


def test_create_invoice_x402_reuses_scheme_build(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.subscription as subs_mod

    captured: dict[str, Any] = {}

    def fake_build_payment_required(
        operation: str,
        resource: str = "",
        accepts: list[dict[str, Any]] | None = None,
        description: str = "",
        mime_type: str = "application/json",
        preferred_networks: list[str] | None = None,
        preferred_assets: list[str] | None = None,
        multi_asset: bool = False,
    ) -> dict[str, Any]:
        captured["operation"] = operation
        captured["accepts"] = accepts
        captured["description"] = description
        return {"x402Version": 1, "accepts": accepts or []}

    monkeypatch.setattr(subs_mod, "build_payment_required", fake_build_payment_required)
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    assert captured["operation"] == "subscription"
    accepts = captured["accepts"]
    assert accepts is not None
    assert len(accepts) == 1
    assert accepts[0]["scheme"] == X402Scheme.EXACT.value
    assert accepts[0]["maxAmountRequired"] == "49000000"
    assert accepts[0]["extra"]["tier"] == "pro"
    assert accepts[0]["extra"]["invoice_id"] == invoice["invoice_id"]
    assert "Pro subscription (1 month(s))" in captured["description"]


# ── Invoice creation: btcpay fallback ─────────────────────────────────────
def test_create_invoice_btcpay(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.subscription as subs_mod

    monkeypatch.setenv("PRY_BTCPAY_URL", "https://btcpayserver.example.com")
    monkeypatch.setenv("PRY_BTCPAY_API_KEY", "test-token")
    monkeypatch.setenv("PRY_BTCPAY_STORE", "store_abc")
    monkeypatch.setattr(
        subs_mod.httpx,
        "post",
        lambda *args, **kwargs: _FakeResponse(
            {
                "id": "btcpay_inv_1",
                "status": "New",
                "amount": "49.00",
                "addresses": {"BTC-OnChain": "bc1qtestaddress"},
            }
        ),
    )
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    assert invoice["payment_method"] == "btcpay"
    assert invoice["invoice_id"] == "btcpay_inv_1"
    assert invoice["chain"] == "bitcoin"
    assert invoice["payment_address"] == "bc1qtestaddress"
    assert invoice["amount_asset"] == "49.00"


def test_create_invoice_btcpay_requires_store_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_BTCPAY_URL", "https://btcpayserver.example.com")
    monkeypatch.setenv("PRY_BTCPAY_API_KEY", "test-token")
    # No PRY_BTCPAY_STORE → degrade to x402 (documented fallback).
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    assert invoice["payment_method"] == "x402"


def test_create_invoice_unknown_or_unpriced_tier_raises() -> None:
    with pytest.raises(ValueError, match="no fixed monthly price"):
        create_subscription_invoice("free", "sk_any")
    with pytest.raises(ValueError, match="no fixed monthly price"):
        create_subscription_invoice("enterprise", "sk_any")
    with pytest.raises(ValueError, match=r"unknown|no fixed"):
        create_subscription_invoice("nonexistent", "sk_any")


def test_create_invoice_invalid_months_raises() -> None:
    with pytest.raises(ValueError, match="months"):
        create_subscription_invoice("pro", "sk_pro_1", months=0)
    with pytest.raises(ValueError, match="months"):
        create_subscription_invoice("pro", "sk_pro_1", months=-1)  # type: ignore[arg-type]


# ── Verify: x402 ──────────────────────────────────────────────────────────
def test_verify_unpaid_x402() -> None:
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    result = verify_subscription_payment(invoice["invoice_id"])
    assert result["paid"] is False
    assert result["tx_hash"] is None
    assert "no payment reported" in result["reason"]


def test_verify_paid_x402(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.subscription as subs_mod

    invoice = create_subscription_invoice("pro", "sk_pro_1")
    submit_subscription_payment(invoice["invoice_id"], "0xdeadbeef")
    fake = _FakeFacilitator(_verified_result())
    monkeypatch.setattr(subs_mod, "_get_self_facilitator", lambda: fake)
    result = verify_subscription_payment(invoice["invoice_id"])
    assert result["paid"] is True
    assert result["tx_hash"] == "0xdeadbeef"
    assert result["confirmed_at"] is not None
    assert len(fake.verified_payments) == 1
    assert fake.verified_payments[0]["amount_usd"] == 49.0


def test_verify_rejected_x402(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.subscription as subs_mod

    invoice = create_subscription_invoice("pro", "sk_pro_1")
    submit_subscription_payment(invoice["invoice_id"], "0xdeadbeef")
    fake = _FakeFacilitator(VerifyResult(verified=False, reason="signature invalid"))
    monkeypatch.setattr(subs_mod, "_get_self_facilitator", lambda: fake)
    result = verify_subscription_payment(invoice["invoice_id"])
    assert result["paid"] is False
    assert "signature invalid" in result["reason"]


def test_verify_expired_x402(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_SUBSCRIPTION_INVOICE_TTL", "1")  # 1-second validity
    base = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, base)
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    _freeze_clock(monkeypatch, base.replace(second=10))
    result = verify_subscription_payment(invoice["invoice_id"])
    assert result["paid"] is False
    assert result["reason"] == "expired"


def test_verify_paid_but_expired_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.subscription as subs_mod

    monkeypatch.setenv("PRY_SUBSCRIPTION_INVOICE_TTL", "1")
    base = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, base)
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    submit_subscription_payment(invoice["invoice_id"], "0xdeadbeef")
    fake = _FakeFacilitator(_verified_result())
    monkeypatch.setattr(subs_mod, "_get_self_facilitator", lambda: fake)
    _freeze_clock(monkeypatch, base.replace(second=10))
    result = verify_subscription_payment(invoice["invoice_id"])
    assert result["paid"] is False
    assert result["reason"] == "expired"


def test_verify_unknown_invoice() -> None:
    result = verify_subscription_payment("inv_does_not_exist")
    assert result["paid"] is False
    assert result["reason"] == "unknown invoice"


def test_submit_payment_validates_inputs() -> None:
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    with pytest.raises(ValueError, match="tx_hash"):
        submit_subscription_payment(invoice["invoice_id"], "  ")
    with pytest.raises(ValueError, match="unknown invoice"):
        submit_subscription_payment("inv_missing", "0xdeadbeef")


# ── Verify: btcpay ────────────────────────────────────────────────────────
def _enable_btcpay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_BTCPAY_URL", "https://btcpayserver.example.com")
    monkeypatch.setenv("PRY_BTCPAY_API_KEY", "test-token")
    monkeypatch.setenv("PRY_BTCPAY_STORE", "store_abc")


def test_verify_btcpay_settled(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.subscription as subs_mod

    _enable_btcpay(monkeypatch)
    monkeypatch.setattr(
        subs_mod.httpx,
        "post",
        lambda *args, **kwargs: _FakeResponse({"id": "bp_1", "status": "New", "amount": "49.00"}),
    )
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    monkeypatch.setattr(
        subs_mod.httpx,
        "get",
        lambda *args, **kwargs: _FakeResponse(
            {
                "id": "bp_1",
                "status": "Settled",
                "payments": [{"transactionId": "0xbtcpaytx"}],
            }
        ),
    )
    result = verify_subscription_payment(invoice["invoice_id"])
    assert result["paid"] is True
    assert result["tx_hash"] == "0xbtcpaytx"
    assert result["confirmed_at"] is not None


def test_verify_btcpay_unsettled(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.subscription as subs_mod

    _enable_btcpay(monkeypatch)
    monkeypatch.setattr(
        subs_mod.httpx,
        "post",
        lambda *args, **kwargs: _FakeResponse({"id": "bp_2", "status": "New", "amount": "49.00"}),
    )
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    monkeypatch.setattr(
        subs_mod.httpx,
        "get",
        lambda *args, **kwargs: _FakeResponse({"id": "bp_2", "status": "New"}),
    )
    result = verify_subscription_payment(invoice["invoice_id"])
    assert result["paid"] is False
    assert result["tx_hash"] is None
    assert "btcpay status New" in result["reason"]


def test_verify_btcpay_settled_after_local_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """BTCPay upstream 'Settled' is authoritative even past our local TTL."""
    import billing.subscription as subs_mod

    _enable_btcpay(monkeypatch)
    monkeypatch.setenv("PRY_SUBSCRIPTION_INVOICE_TTL", "1")
    base = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, base)
    monkeypatch.setattr(
        subs_mod.httpx,
        "post",
        lambda *args, **kwargs: _FakeResponse({"id": "bp_3", "status": "New", "amount": "49.00"}),
    )
    invoice = create_subscription_invoice("pro", "sk_pro_1")
    _freeze_clock(monkeypatch, base.replace(day=20))
    monkeypatch.setattr(
        subs_mod.httpx,
        "get",
        lambda *args, **kwargs: _FakeResponse(
            {"id": "bp_3", "status": "Settled", "payments": [{"transactionId": "0xbptx"}]}
        ),
    )
    result = verify_subscription_payment(invoice["invoice_id"])
    assert result["paid"] is True
    assert result["tx_hash"] == "0xbptx"


# ── Activate + status ─────────────────────────────────────────────────────
def test_activate_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    base = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, base)
    result = activate_subscription("sk_pro_1", "pro", 1)
    assert result["tier"] == "pro"
    assert result["expires_at"].startswith("2026-02-15")

    status = subscription_status("sk_pro_1")
    assert status["tier"] == "pro"
    assert status["active"] is True
    assert status["expires_at"].startswith("2026-02-15")
    assert "month_requests" in status["usage"]


def test_status_unknown_key_is_free() -> None:
    status = subscription_status("nobody")
    assert status["tier"] == "free"
    assert status["active"] is False
    assert status["expires_at"] is None


def test_activate_expiry_rollover(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.subscription as subs_mod

    base = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, base)
    activate_subscription("sk_roll", "team", 1)
    # Renewal while still active extends from the CURRENT expiry, not from now.
    _freeze_clock(monkeypatch, base.replace(day=20))
    second = activate_subscription("sk_roll", "team", 2)
    assert second["expires_at"].startswith("2026-04-15")  # Feb 15 + 2 calendar months

    # After expiry, re-activation restarts from now.
    _freeze_clock(monkeypatch, datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC))
    assert subscription_status("sk_roll")["active"] is False
    third = activate_subscription("sk_roll", "team", 1)
    assert third["expires_at"].startswith("2026-06-01")
    assert subs_mod._SUBSCRIPTIONS["sk_roll"]["tier"] == "team"


def test_activate_downgrade_restarts_from_now(monkeypatch: pytest.MonkeyPatch) -> None:
    base = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    _freeze_clock(monkeypatch, base)
    activate_subscription("sk_switch", "team", 6)  # expires Jul 15
    _freeze_clock(monkeypatch, base.replace(day=20))
    result = activate_subscription("sk_switch", "pro", 1)  # different tier → from now
    assert result["expires_at"].startswith("2026-02-20")


def test_activate_unpriced_tier_raises() -> None:
    with pytest.raises(ValueError, match="no fixed monthly price"):
        activate_subscription("sk_any", "free", 1)
    with pytest.raises(ValueError, match="no fixed monthly price"):
        activate_subscription("sk_any", "enterprise", 1)


# ── Persistence roundtrip ─────────────────────────────────────────────────
def test_persistence_roundtrip(tmp_path: Path) -> None:
    store = tmp_path / "subscriptions.json"
    set_subscription_store_path(store)
    activated = activate_subscription("sk_persist", "pro", 2)
    invoice_id = create_subscription_invoice("pro", "sk_persist")["invoice_id"]
    assert store.exists()

    # Simulate a process restart: registries are empty, state must reload.
    reset_subscription_state()
    status = subscription_status("sk_persist")
    assert status["tier"] == "pro"
    assert status["active"] is True
    assert status["expires_at"] == activated["expires_at"]

    # Invoices survive the roundtrip too.
    import billing.subscription as subs_mod

    assert invoice_id in subs_mod._INVOICES  # reloaded from disk on read above
    assert verify_subscription_payment(invoice_id)["reason"] != "unknown invoice"


def test_persistence_disabled_without_path() -> None:
    set_subscription_store_path(None)
    activate_subscription("sk_mem", "pro", 1)
    reset_subscription_state()
    status = subscription_status("sk_mem")
    assert status["active"] is False  # nothing persisted → gone after reset
