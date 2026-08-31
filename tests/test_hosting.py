# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for cloud hosting signup + checkout (x402 crypto checkout + provisioning).

Covers:
- hosting plan catalog matches the billing tiers (pro $49 / team $199 / enterprise custom)
- signup invoice returns a 402 manifest quoting a real treasury payTo
  (and fails closed with no placeholder payTo when the wallet is unconfigured)
- confirmed payment provisions a HostedInstance + mints an API key + credits the ledger
- underpayment is rejected (never provisioned, never credited)
- instance lifecycle: get / list / suspend / cancel / renew (renewal extends expiry)
- route-level: signup manifest, confirm, instance list/detail scoped by API key
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import pry.commerce.hosting as hosting_mod
from pry.api.api import app
from pry.commerce import billing_service
from pry.commerce.hosting import (
    InstanceNotFound,
    WalletUnconfigured,
    cancel_instance,
    confirm_hosting_payment_sync,
    create_hosting_signup,
    get_instance,
    list_instances,
    list_plans,
    renew_instance,
    reset_hosting_state,
    suspend_instance,
)
from pry.payments.x402.self_facilitator import VerifyResult

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"


class _FakeFacilitator:
    """Scripted SelfFacilitator double for hosting verify + settle."""

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


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB for instances + ledger (same pattern as test_billing_packs)."""
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
def _clean_hosting_state(monkeypatch):
    """Reset the invoice registry + wire a real treasury wallet."""
    reset_hosting_state()
    monkeypatch.setattr(hosting_mod, "X402_NETWORK_WALLETS", {"eip155:8453": _REAL_WALLET})
    monkeypatch.setattr(hosting_mod, "X402_WALLET", _REAL_WALLET)
    yield
    reset_hosting_state()


# ── Plans ───────────────────────────────────────────────────────────────────
def test_plan_catalog_matches_tiers() -> None:
    plans = {p["tier"]: p for p in list_plans()}
    assert set(plans) == {"pro", "team", "enterprise"}
    assert plans["pro"]["price_usd_monthly"] == 49.0
    assert plans["pro"]["max_concurrent_scrapes"] == 100
    assert plans["pro"]["max_pages_month"] == 100_000
    assert plans["pro"]["storage_gb"] == 10
    assert plans["team"]["price_usd_monthly"] == 199.0
    assert plans["team"]["max_concurrent_scrapes"] == 500
    assert plans["team"]["max_pages_month"] == 500_000
    assert plans["team"]["storage_gb"] == 50
    assert plans["enterprise"]["price_usd_monthly"] is None  # custom quote
    assert plans["enterprise"]["purchasable"] is False


def test_unknown_plan_raises() -> None:
    import pytest

    with pytest.raises(hosting_mod.PlanNotFound):
        create_hosting_signup("buyer@example.com", "nonexistent")


# ── Fail-closed wallet rule ────────────────────────────────────────────────
def test_signup_fails_closed_without_wallet(monkeypatch) -> None:
    monkeypatch.setattr(hosting_mod, "X402_NETWORK_WALLETS", {"eip155:8453": ""})
    monkeypatch.setattr(hosting_mod, "X402_WALLET", "")
    with pytest.raises(WalletUnconfigured):
        create_hosting_signup("buyer@example.com", "pro")


def test_signup_emits_real_payto() -> None:
    invoice = create_hosting_signup("buyer@example.com", "pro")
    assert invoice["pay_to"] == _REAL_WALLET
    assert invoice["payment_required"]["accepts"][0]["payToAddress"] == _REAL_WALLET
    assert invoice["amount_usd"] == 49.0
    assert invoice["amount_atomic"] == 49_000_000
    assert invoice["invoice_id"].startswith("host_")
    assert invoice["plan_tier"] == "pro"


def test_enterprise_signup_rejected() -> None:
    with pytest.raises(hosting_mod.PlanNotPurchasable):
        create_hosting_signup("buyer@example.com", "enterprise")


# ── Signup → confirm → provision ───────────────────────────────────────────
def test_confirm_provisions_instance_and_mints_key(db, monkeypatch) -> None:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = create_hosting_signup("buyer@example.com", "pro")
    result = confirm_hosting_payment_sync(invoice["invoice_id"], "0xdeadbeef")

    assert result["paid"] is True
    assert result["api_key"]  # plaintext shown once
    assert result["api_key"].startswith("pry_")
    instance = result["instance"]
    assert instance["plan_tier"] == "pro"
    assert instance["status"] == "active"
    assert instance["resource_limit"]["max_concurrent_scrapes"] == 100
    assert instance["resource_limit"]["max_pages_month"] == 100_000
    assert instance["resource_limit"]["storage_gb"] == 10
    assert instance["api_key_id"]  # key reference stored, never the plaintext
    assert instance["api_key_id"] != result["api_key"]

    # Ledger credited with the plan price.
    balance = billing_service.get_balance(instance["user_id"])
    assert balance["balance_usd"] == 49.0
    deposit = billing_service.ledger(instance["user_id"])[0]
    assert deposit["reason"] == "deposit"
    assert deposit["reference"].startswith("hosting:")

    # User account created from the email.
    from pry.core.db import models as models_mod
    from pry.core.db.session import get_session

    with get_session() as session:
        user = session.query(models_mod.User).filter_by(user_id=instance["user_id"]).first()
        assert user is not None
        assert user.email == "buyer@example.com"


def test_underpayment_rejected(db, monkeypatch) -> None:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_unverified_result())
    )
    invoice = create_hosting_signup("under@example.com", "pro")
    with pytest.raises(hosting_mod.Underpayment):
        confirm_hosting_payment_sync(invoice["invoice_id"], "0xunderpay")
    # No instance, no credit.
    assert (
        list_instances(
            "host_" + __import__("hashlib").sha256(b"under@example.com").hexdigest()[:12]
        )
        == []
    )


def test_no_payment_reported_is_never_provisioned(db) -> None:
    invoice = create_hosting_signup("nopay@example.com", "team")
    with pytest.raises(ValueError, match="payment_proof"):
        confirm_hosting_payment_sync(invoice["invoice_id"], "")  # empty proof
    # No tx reported: verify alone reports unpaid, nothing provisioned.
    assert list_instances("host_nopay") == []


# ── Instance lifecycle ──────────────────────────────────────────────────────
def _provision(
    db, monkeypatch, email: str = "life@example.com", tier: str = "pro"
) -> dict[str, Any]:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = create_hosting_signup(email, tier)
    return confirm_hosting_payment_sync(invoice["invoice_id"], "0x" + "a" * 8)


def test_get_and_list_instances(db, monkeypatch) -> None:
    result = _provision(db, monkeypatch, email="list@example.com", tier="team")
    instance = result["instance"]
    detail = get_instance(instance["instance_id"])
    assert detail["instance_id"] == instance["instance_id"]
    assert detail["active"] is True
    assert detail["plan_tier"] == "team"

    listed = list_instances(instance["user_id"])
    assert [i["instance_id"] for i in listed] == [instance["instance_id"]]

    with pytest.raises(InstanceNotFound):
        get_instance("inst_doesnotexist")


def test_suspend_instance(db, monkeypatch) -> None:
    result = _provision(db, monkeypatch)
    instance_id = result["instance"]["instance_id"]
    suspended = suspend_instance(instance_id)
    assert suspended["status"] == "suspended"
    assert get_instance(instance_id)["active"] is False
    # Idempotent.
    assert suspend_instance(instance_id)["status"] == "suspended"


def test_cancel_instance(db, monkeypatch) -> None:
    result = _provision(db, monkeypatch)
    instance_id = result["instance"]["instance_id"]
    assert cancel_instance(instance_id)["status"] == "cancelled"


def test_renew_extends_expiry(db, monkeypatch) -> None:
    result = _provision(db, monkeypatch)
    instance_id = result["instance"]["instance_id"]
    before = get_instance(instance_id)["expires_at"]

    renewal = renew_instance(instance_id)
    assert renewal["invoice_id"].startswith("host_")
    assert renewal["instance_id"] == instance_id
    assert renewal["amount_usd"] == 49.0
    assert renewal["payment_required"]["accepts"][0]["payToAddress"] == _REAL_WALLET

    confirmed = confirm_hosting_payment_sync(renewal["invoice_id"], "0x" + "b" * 8)
    assert confirmed["paid"] is True
    assert confirmed["api_key"] is None  # renewal: no new key minted
    assert confirmed["instance"]["instance_id"] == instance_id

    after = get_instance(instance_id)
    assert after["expires_at"] > before  # expiry rolled forward
    assert after["status"] == "active"

    # Exactly one instance (renewal does not provision a duplicate).
    assert len(list_instances(result["instance"]["user_id"])) == 1


def test_renew_unknown_instance_raises(db) -> None:
    with pytest.raises(InstanceNotFound):
        renew_instance("inst_doesnotexist")


def test_renewal_clears_suspension(db, monkeypatch) -> None:
    result = _provision(db, monkeypatch)
    instance_id = result["instance"]["instance_id"]
    suspend_instance(instance_id)
    renewal = renew_instance(instance_id)
    confirmed = confirm_hosting_payment_sync(renewal["invoice_id"], "0x" + "c" * 8)
    assert confirmed["instance"]["status"] == "active"


# ── Route-level ─────────────────────────────────────────────────────────────
@pytest.fixture
def client() -> TestClient:
    # No `with`: skip the lifespan so the strict x402 route-classification
    # audit is not triggered here (same pattern as test_subscription_route).
    return TestClient(app)


def test_route_plans(client: TestClient) -> None:
    resp = client.get("/v1/hosting/plans")
    assert resp.status_code == 200
    tiers = {p["tier"] for p in resp.json()["data"]["plans"]}
    assert tiers == {p["tier"] for p in list_plans()}


def test_route_signup_returns_402_manifest(client: TestClient) -> None:
    resp = client.post(
        "/v1/hosting/signup",
        json={"user_email": "route@example.com", "plan_tier": "pro"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status_code"] == 402
    assert data["pay_to"] == _REAL_WALLET
    assert data["amount_usd"] == 49.0
    assert data["payment_required"]["accepts"][0]["payToAddress"] == _REAL_WALLET


def test_route_signup_fails_closed_503(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(hosting_mod, "X402_NETWORK_WALLETS", {"eip155:8453": ""})
    monkeypatch.setattr(hosting_mod, "X402_WALLET", "")
    resp = client.post(
        "/v1/hosting/signup",
        json={"user_email": "route@example.com", "plan_tier": "pro"},
    )
    assert resp.status_code == 503


def test_route_signup_unknown_plan_404(client: TestClient) -> None:
    resp = client.post(
        "/v1/hosting/signup",
        json={"user_email": "route@example.com", "plan_tier": "bogus"},
    )
    assert resp.status_code == 404


def test_route_full_signup_flow(client: TestClient, db, monkeypatch) -> None:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    resp = client.post(
        "/v1/hosting/signup",
        json={"user_email": "flow@example.com", "plan_tier": "team"},
    )
    invoice_id = resp.json()["data"]["invoice_id"]
    confirm = client.post(
        f"/v1/hosting/signup/{invoice_id}/confirm",
        json={"tx_hash": "0x" + "c" * 8},
    )
    assert confirm.status_code == 200
    data = confirm.json()["data"]
    assert data["paid"] is True
    assert data["api_key"].startswith("pry_")
    instance_id = data["instance"]["instance_id"]

    # Instance list + detail scoped by the minted key.
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    listed = client.get("/v1/hosting/instances", headers=headers)
    assert listed.status_code == 200
    assert [i["instance_id"] for i in listed.json()["data"]["instances"]] == [instance_id]

    detail = client.get(f"/v1/hosting/instances/{instance_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["instance"]["plan_tier"] == "team"

    # Foreign / bad keys are rejected.
    assert (
        client.get("/v1/hosting/instances", headers={"Authorization": "Bearer pry_bad"}).status_code
        == 401
    )
    assert client.get("/v1/hosting/instances").status_code == 401

    # Renewal invoice via the route.
    renew = client.post(f"/v1/hosting/instances/{instance_id}/renew", headers=headers)
    assert renew.status_code == 200
    assert renew.json()["data"]["status_code"] == 402

    # Cancel via the route.
    cancel = client.post(f"/v1/hosting/instances/{instance_id}/cancel", headers=headers)
    assert cancel.status_code == 200
    assert cancel.json()["data"]["instance"]["status"] == "cancelled"


def test_route_confirm_underpayment_rejected(client: TestClient, db, monkeypatch) -> None:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_unverified_result())
    )
    resp = client.post(
        "/v1/hosting/signup",
        json={"user_email": "under2@example.com", "plan_tier": "pro"},
    )
    invoice_id = resp.json()["data"]["invoice_id"]
    confirm = client.post(
        f"/v1/hosting/signup/{invoice_id}/confirm",
        json={"tx_hash": "0xunderpay"},
    )
    assert confirm.status_code == 200
    body = confirm.json()
    assert body["success"] is False
    assert body["data"]["paid"] is False


def test_route_confirm_unknown_invoice_404(client: TestClient) -> None:
    resp = client.post(
        "/v1/hosting/signup/host_doesnotexist/confirm",
        json={"tx_hash": "0xabc"},
    )
    assert resp.status_code == 404


# ── Coverage-gap tests: expired-instance renewal + cancel semantics ─────────
def test_renew_expired_instance_extends_from_now(db, monkeypatch) -> None:
    """An expired instance renewed via a renewal invoice rolls expiry forward
    from *now* (not from the stale past expiry) and reactivates."""
    from datetime import UTC, datetime, timedelta

    from pry.core.db.models import HostedInstance
    from pry.core.db.session import get_session

    result = _provision(db, monkeypatch, email="expired@example.com")
    instance_id = result["instance"]["instance_id"]

    # Force the instance into the past (expired).
    with get_session() as session:
        row = session.query(HostedInstance).filter_by(instance_id=instance_id).first()
        row.expires_at = datetime.now(UTC) - timedelta(days=30)
        session.commit()
    assert get_instance(instance_id)["active"] is False

    renewal = renew_instance(instance_id)
    confirmed = confirm_hosting_payment_sync(renewal["invoice_id"], "0x" + "e" * 8)
    assert confirmed["paid"] is True
    assert confirmed["instance"]["instance_id"] == instance_id

    after = get_instance(instance_id)
    assert after["active"] is True
    # New expiry is ~1 month from now, not from the stale past expiry.
    new_expiry = datetime.fromisoformat(after["expires_at"])
    assert new_expiry > datetime.now(UTC) + timedelta(days=27)
    assert new_expiry < datetime.now(UTC) + timedelta(days=32)


def test_cancel_active_instance(db, monkeypatch) -> None:
    """Cancelling an active instance marks it cancelled and inactive."""
    result = _provision(db, monkeypatch, email="cancel@example.com")
    instance_id = result["instance"]["instance_id"]
    assert get_instance(instance_id)["active"] is True

    cancelled = cancel_instance(instance_id)
    assert cancelled["status"] == "cancelled"
    assert get_instance(instance_id)["active"] is False
    with pytest.raises(InstanceNotFound):
        cancel_instance("inst_nope")
