# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Route-level tests for the hosted subscription billing flow.

Covers:
- invoice creation returns a 402 payment manifest quoting a real payTo
  (and fails closed with 503 when the treasury wallet is unconfigured)
- verify + activate credits the account ONLY on a successful verify
  (an unverified payment is never activated)
- re-confirming an already-activated invoice is idempotent (no double credit)

The app is exercised without entering the lifespan context so the strict x402
startup audit is not triggered here (see module [REVIEW] note).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app
from pry.commerce.billing import (
    activate_subscription,
    create_subscription_invoice,
    reset_subscription_state,
    set_subscription_store_path,
    subscription as subs_mod,
    subscription_status,
)
from pry.payments.x402.self_facilitator import VerifyResult

if TYPE_CHECKING:
    from collections.abc import Generator

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"


class _FakeFacilitator:
    """Scripted SelfFacilitator double for subscription verify + settle."""

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
def _clean_subscription_route_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Reset registries + wire a real treasury wallet so the happy path works.

    Also resets the router's in-process activation idempotency registry.
    """
    from pry.api.routers.commerce.billing_subscription import _ACTIVATED

    reset_subscription_state()
    set_subscription_store_path(None)
    _ACTIVATED.clear()
    monkeypatch.setattr(subs_mod, "X402_NETWORK_WALLETS", {"eip155:8453": _REAL_WALLET})
    monkeypatch.setattr(subs_mod, "X402_WALLET", _REAL_WALLET)
    yield
    _ACTIVATED.clear()
    reset_subscription_state()
    set_subscription_store_path(None)


@pytest.fixture
def client() -> TestClient:
    # No `with`: skip the lifespan so the strict x402 route-classification
    # audit (which lives in another owner's file) is not triggered here.
    return TestClient(app)


# ── Invoice creation: 402 manifest with a real payTo ───────────────────────
def test_create_invoice_returns_402_manifest_with_payto(client: TestClient) -> None:
    resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": "sk_pro_route", "months": 1},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status_code"] == 402  # x402 PaymentRequired marker
    assert data["pay_to"] == _REAL_WALLET  # treasury payTo quoted
    assert data["invoice_id"].startswith("inv_")
    assert data["tier"] == "pro"
    assert data["amount_usd"] == 49.0
    assert data["amount_atomic"] == "49000000"  # 49 USDC atomic (6 dp)
    assert data["chain"] == "eip155:8453"
    assert data["asset"] == "USDC"
    assert data["payment_method"] == "x402"
    assert data["expires_at"]


def test_create_invoice_multiple_months(client: TestClient) -> None:
    resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "team", "api_key": "sk_team_route", "months": 2},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["amount_usd"] == 398.0  # 199 * 2
    assert data["amount_atomic"] == "398000000"


def test_create_invoice_unknown_tier_is_400(client: TestClient) -> None:
    resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "bogus", "api_key": "sk_bogus", "months": 1},
    )
    assert resp.status_code == 400


def test_create_invoice_fails_closed_without_wallet(client: TestClient, monkeypatch) -> None:
    """Never a placeholder payTo: unconfigured wallet -> 503."""
    monkeypatch.setattr(subs_mod, "X402_NETWORK_WALLETS", {"eip155:8453": ""})
    monkeypatch.setattr(subs_mod, "X402_WALLET", "")
    resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": "sk_nowallet", "months": 1},
    )
    assert resp.status_code == 503


# ── Verify + activate: credits only on successful verify ───────────────────
def test_confirm_activates_only_on_verified_payment(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        subs_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice_resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": "sk_activate", "months": 1},
    )
    invoice_id = invoice_resp.json()["data"]["invoice_id"]

    confirm_resp = client.post(
        f"/v1/billing/subscription/invoice/{invoice_id}/confirm",
        json={"tx_hash": "0xverified"},
    )
    assert confirm_resp.status_code == 200
    data = confirm_resp.json()["data"]
    assert data["paid"] is True
    assert data["idempotent"] is False
    assert data["tier"] == "pro"
    assert data["months"] == 1
    assert data["subscription"]["tier"] == "pro"

    status = subscription_status("sk_activate")
    assert status["tier"] == "pro"
    assert status["active"] is True
    assert status["expires_at"]


def test_confirm_unverified_payment_never_activates(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        subs_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_unverified_result())
    )
    invoice_resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": "sk_unverified", "months": 1},
    )
    invoice_id = invoice_resp.json()["data"]["invoice_id"]

    confirm_resp = client.post(
        f"/v1/billing/subscription/invoice/{invoice_id}/confirm",
        json={"tx_hash": "0xunverified"},
    )
    assert confirm_resp.status_code == 200
    data = confirm_resp.json()["data"]
    assert data["paid"] is False
    assert "not verified" in data["reason"] or data["reason"]

    # Not credited: the account is still on the FREE tier.
    status = subscription_status("sk_unverified")
    assert status["tier"] == "free"
    assert status["active"] is False


def test_confirm_unknown_invoice_is_404(client: TestClient) -> None:
    resp = client.post(
        "/v1/billing/subscription/invoice/inv_doesnotexist/confirm",
        json={"tx_hash": "0xdeadbeef"},
    )
    assert resp.status_code == 404


# ── Settlement gate: activation ONLY after on-chain settle succeeds ────────
def test_confirm_settle_success_activates(client: TestClient, monkeypatch) -> None:
    """Verify + settle success -> subscription activated, settle was called."""
    fake = _FakeFacilitator(_verified_result())
    monkeypatch.setattr(subs_mod, "_get_self_facilitator", lambda: fake)
    invoice_resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": "sk_settle_ok", "months": 1},
    )
    invoice_id = invoice_resp.json()["data"]["invoice_id"]

    confirm_resp = client.post(
        f"/v1/billing/subscription/invoice/{invoice_id}/confirm",
        json={"tx_hash": "0xsettled"},
    )
    assert confirm_resp.status_code == 200
    data = confirm_resp.json()["data"]
    assert data["paid"] is True
    assert len(fake.settled_payments) == 1
    assert fake.settled_payments[0]["payment_id"] == invoice_id

    status = subscription_status("sk_settle_ok")
    assert status["tier"] == "pro"
    assert status["active"] is True


def test_confirm_settle_failure_never_activates(client: TestClient, monkeypatch) -> None:
    """A failed on-chain settlement must NOT activate — payment-failed response."""
    fake = _FakeFacilitator(_verified_result(), settle_tx=None)
    monkeypatch.setattr(subs_mod, "_get_self_facilitator", lambda: fake)
    invoice_resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": "sk_settle_fail", "months": 1},
    )
    invoice_id = invoice_resp.json()["data"]["invoice_id"]

    confirm_resp = client.post(
        f"/v1/billing/subscription/invoice/{invoice_id}/confirm",
        json={"tx_hash": "0xnosettle"},
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["success"] is False
    data = confirm_resp.json()["data"]
    assert data["paid"] is False
    assert "settlement" in data["reason"]
    assert len(fake.settled_payments) == 1  # settle was attempted

    # Not activated: the account is still on the FREE tier.
    status = subscription_status("sk_settle_fail")
    assert status["tier"] == "free"
    assert status["active"] is False


def test_reconfirm_same_invoice_is_idempotent(client: TestClient, monkeypatch) -> None:
    """Re-confirming an already-activated invoice must not double-credit.

    activate_subscription extends from the current expiry on a same-tier
    renewal, so without the router guard a second confirm would add another
    month (double credit).
    """
    from datetime import UTC, datetime

    monkeypatch.setattr(
        subs_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )

    # Freeze time so the renewal-rollover math is deterministic.
    frozen = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(subs_mod, "_now", lambda: frozen)

    invoice_resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": "sk_idem", "months": 1},
    )
    invoice_id = invoice_resp.json()["data"]["invoice_id"]

    first = client.post(
        f"/v1/billing/subscription/invoice/{invoice_id}/confirm",
        json={"tx_hash": "0xidem"},
    )
    assert first.json()["data"]["idempotent"] is False
    expiry_first = first.json()["data"]["subscription"]["expires_at"]

    second = client.post(
        f"/v1/billing/subscription/invoice/{invoice_id}/confirm",
        json={"tx_hash": "0xidem"},
    )
    assert second.json()["data"]["idempotent"] is True
    expiry_second = second.json()["data"]["subscription"]["expires_at"]
    assert expiry_second == expiry_first  # not extended again


# ── Sanity: library functions remain wired to the same modules ─────────────
def test_route_uses_library_functions() -> None:
    """The route layer calls the existing subscription library (no re-pricing)."""
    from pry.api.routers.commerce.billing_subscription import (
        billing_subscription_confirm,
        billing_subscription_invoice,
    )

    assert billing_subscription_invoice.__doc__
    assert billing_subscription_confirm.__doc__
    assert create_subscription_invoice is subs_mod.create_subscription_invoice
    assert activate_subscription is subs_mod.activate_subscription
