# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Integration tests for the full x402 customer journey.

signup → pay → verify → access → cancel, plus the self-service account
surface (usage / billing history / balance) and the password-reset flow.

All external effects are mocked: the self-facilitator is replaced with a
scripted double (no blockchain calls) and the database is an isolated
per-test SQLite file. Route-level tests use TestClient against the real
app WITHOUT entering the lifespan context (same pattern as
test_subscription_route.py) so the strict x402 startup audit is skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app
from pry.commerce.billing import (
    subscription as subs_mod,
    subscription_status,
)
from pry.core import api_keys_service as svc
from pry.payments.x402.self_facilitator import VerifyResult

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"


class _FakeFacilitator:
    """Scripted SelfFacilitator double for subscription verify + settle."""

    def __init__(
        self,
        result: VerifyResult,
        *,
        settle_tx: str | None = "0x" + "f" * 64,
    ) -> None:
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


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite DB (same engine-reset pattern as test_earnings)."""
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
def _clean_customer_flow_state(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Reset subscription registries + wire a real treasury wallet.

    Also clears the billing router's in-process idempotency / auto-renew /
    pending-tier registries and the auth router's reset-token cache.
    """
    from pry.api.routers.commerce.billing_subscription import (
        _ACTIVATED,
        _AUTO_RENEW,
        _PENDING_TIER,
    )
    from pry.api.routers.core import auth as auth_mod

    subs_mod.reset_subscription_state()
    subs_mod.set_subscription_store_path(None)
    _ACTIVATED.clear()
    _AUTO_RENEW.clear()
    _PENDING_TIER.clear()
    auth_mod._RESET_TOKENS.clear()
    monkeypatch.setattr(subs_mod, "X402_NETWORK_WALLETS", {"eip155:8453": _REAL_WALLET})
    monkeypatch.setattr(subs_mod, "X402_WALLET", _REAL_WALLET)
    yield
    _ACTIVATED.clear()
    _AUTO_RENEW.clear()
    _PENDING_TIER.clear()
    auth_mod._RESET_TOKENS.clear()
    subs_mod.reset_subscription_state()
    subs_mod.set_subscription_store_path(None)


@pytest.fixture
def client() -> TestClient:
    # No `with`: skip the lifespan so the strict x402 route-classification
    # audit (which lives in another owner's file) is not triggered here.
    return TestClient(app)


def _signup(db, user_id: str = "cust_flow", tier: str = "FREE") -> dict[str, Any]:
    """Create a user + API key (the signup step of the journey)."""
    return svc.issue_key(user_id=user_id, name="customer", tier=tier)


def _auth_headers(plaintext: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {plaintext}"}


def _activate_pro(client: TestClient, api_key: str, monkeypatch) -> str:
    """Create + confirm a pro invoice so the subscription is active."""
    monkeypatch.setattr(
        subs_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": api_key, "months": 1},
    ).json()["data"]
    confirm = client.post(
        f"/v1/billing/subscription/invoice/{invoice['invoice_id']}/confirm",
        json={"tx_hash": "0xverified"},
    )
    assert confirm.json()["data"]["paid"] is True
    return invoice["invoice_id"]


# ── 1. Signup → API key ───────────────────────────────────────────────────


def test_signup_and_get_api_key(db, client: TestClient) -> None:
    """Signup issues a working FREE-tier key that authenticates and can
    reach an authenticated free-tier endpoint."""
    issued = _signup(db, user_id="cust_signup")
    plaintext = issued["plaintext"]
    assert plaintext.startswith("pry_")

    record = svc.authenticate(plaintext)
    assert record is not None
    assert record["user_id"] == "cust_signup"
    assert record["key_id"] == issued["key_id"]

    # The key works through the real middleware on an authenticated
    # free-tier endpoint (account self-service).
    resp = client.get("/v1/account/usage", headers=_auth_headers(plaintext))
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── 2. Create subscription invoice ────────────────────────────────────────


def test_create_subscription_invoice(db, client: TestClient) -> None:
    issued = _signup(db, user_id="cust_invoice")
    resp = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": issued["key_id"], "months": 1},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status_code"] == 402  # x402 PaymentRequired manifest
    assert data["invoice_id"].startswith("inv_")
    assert data["tier"] == "pro"
    assert data["amount_usd"] == 49.0
    assert data["amount_atomic"] == "49000000"  # 49 USDC atomic (6 dp)
    assert data["chain"] == "eip155:8453"
    assert data["asset"] == "USDC"
    assert data["pay_to"] == _REAL_WALLET
    assert data["expires_at"]


# ── 3. Confirm payment → subscription activated ───────────────────────────


def test_confirm_subscription_payment(db, client: TestClient, monkeypatch) -> None:
    issued = _signup(db, user_id="cust_confirm")
    fake = _FakeFacilitator(_verified_result())
    monkeypatch.setattr(subs_mod, "_get_self_facilitator", lambda: fake)

    invoice = client.post(
        "/v1/billing/subscription/invoice",
        json={"tier": "pro", "api_key": issued["key_id"], "months": 1},
    ).json()["data"]

    resp = client.post(
        f"/v1/billing/subscription/invoice/{invoice['invoice_id']}/confirm",
        json={"tx_hash": "0xverified"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["paid"] is True
    assert data["idempotent"] is False
    assert data["tier"] == "pro"
    assert data["months"] == 1
    assert data["subscription"]["tier"] == "pro"
    assert data["subscription"]["expires_at"]

    # The subscription is actually activated for the paying key.
    status = subscription_status(issued["key_id"])
    assert status["tier"] == "pro"
    assert status["active"] is True
    assert status["expires_at"]


# ── 4. Subscription status ────────────────────────────────────────────────


def test_subscription_status(db, client: TestClient, monkeypatch) -> None:
    issued = _signup(db, user_id="cust_status")
    _activate_pro(client, issued["key_id"], monkeypatch)

    resp = client.get("/v1/billing/subscription/status", params={"api_key": issued["key_id"]})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["tier"] == "pro"
    assert data["status"] == "active"
    assert data["current_period_end"]
    assert data["auto_renew"] is True


# ── 5. Cancel subscription ────────────────────────────────────────────────


def test_cancel_subscription(db, client: TestClient, monkeypatch) -> None:
    issued = _signup(db, user_id="cust_cancel")
    _activate_pro(client, issued["key_id"], monkeypatch)
    period_end = subscription_status(issued["key_id"])["expires_at"]

    resp = client.post(
        "/v1/billing/subscription/cancel",
        json={"api_key": issued["key_id"]},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["success"] is True
    assert data["access_until"] == period_end  # access kept until period end

    # Status now reports cancelled with auto-renew off.
    status = client.get(
        "/v1/billing/subscription/status", params={"api_key": issued["key_id"]}
    ).json()["data"]
    assert status["status"] == "cancelled"
    assert status["auto_renew"] is False


# ── 6. Renew subscription ─────────────────────────────────────────────────


def test_renew_subscription(db, client: TestClient, monkeypatch) -> None:
    issued = _signup(db, user_id="cust_renew")
    original_invoice = _activate_pro(client, issued["key_id"], monkeypatch)

    resp = client.post(
        "/v1/billing/subscription/renew",
        json={"api_key": issued["key_id"], "months": 1},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status_code"] == 402
    assert data["invoice_id"].startswith("inv_")
    assert data["invoice_id"] != original_invoice  # a NEW invoice
    assert data["tier"] == "pro"
    assert data["amount_usd"] == 49.0
    assert data["pay_to"] == _REAL_WALLET


# ── 7. Change tier (upgrade prorates) ─────────────────────────────────────


def test_change_tier_upgrade(db, client: TestClient, monkeypatch) -> None:
    issued = _signup(db, user_id="cust_upgrade")
    _activate_pro(client, issued["key_id"], monkeypatch)

    resp = client.post(
        "/v1/billing/subscription/change-tier",
        json={"api_key": issued["key_id"], "new_tier": "team"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["success"] is True
    assert data["new_tier"] == "team"
    # Pro ($49) → Team ($199): the prorated adjustment is strictly positive.
    assert data["price_adjustment"] > 0
    assert data["expires_at"]

    status = subscription_status(issued["key_id"])
    assert status["tier"] == "team"
    assert status["active"] is True


# ── 8. Password reset flow ────────────────────────────────────────────────


def test_password_reset_flow(db, client: TestClient) -> None:
    from pry.api.routers.core import auth as auth_mod
    from pry.core.db.models_auth import User
    from pry.core.db.session import get_session

    email = "reset.flow@example.com"
    with get_session() as session:
        user = User(user_id="cust_reset", email=email, password_hash="old-hash")
        session.add(user)
        session.commit()

    # Request the reset token. The endpoint declares a single Body(...)
    # param, so the JSON body is the raw email value (no embedding).
    resp = client.post("/v1/auth/reset-password", json=email)
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    tokens = list(auth_mod._RESET_TOKENS)
    assert len(tokens) == 1
    token = tokens[0]

    # Confirm with the token + new password.
    confirm = client.post(
        "/v1/auth/reset-password/confirm",
        json={"token": token, "new_password": "new-secret-pw-9"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["success"] is True

    # Password actually changed (PBKDF2-verified) and token consumed.
    with get_session() as session:
        row = session.query(User).filter_by(user_id="cust_reset").first()
        assert row is not None
        assert row.password_hash != "old-hash"
        assert auth_mod._verify_password("new-secret-pw-9", str(row.password_hash))
    assert token not in auth_mod._RESET_TOKENS


# ── 9. Account usage ──────────────────────────────────────────────────────


def test_account_usage(db, client: TestClient) -> None:
    from pry.core.db.models_auth import Usage
    from pry.core.db.session import get_session

    issued = _signup(db, user_id="cust_usage")
    user_id = issued["user_id"]

    # Simulate metered API calls (the middleware normally writes these).
    with get_session() as session:
        for op in ("scrape", "scrape", "crawl"):
            session.add(Usage(user_id=user_id, api_key_id=issued["key_id"], operation=op))
        session.commit()

    resp = client.get("/v1/account/usage", headers=_auth_headers(issued["plaintext"]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["calls_this_month"] == 3
    expected = {"scrape": 2, "crawl": 1}
    assert data["calls_by_endpoint"] == expected
    assert data["tier"] == "FREE"
    assert data["quota_limit"] == 10_000
    assert data["quota_remaining"] == 10_000 - 3
    assert data["reset_date"]


# ── 10. Account billing history ───────────────────────────────────────────


def test_account_billing_history(db, client: TestClient) -> None:
    from pry.core.db.models_billing import LedgerEntry, X402SettlementRecord
    from pry.core.db.session import get_session

    issued = _signup(db, user_id="cust_history")
    user_id = issued["user_id"]

    # A mocked payment: a settled x402 transaction attributed to the user.
    with get_session() as session:
        session.add(
            LedgerEntry(
                user_id=user_id,
                delta_usd=10.0,
                reason="deposit",
                reference="tx_deposit_1",
                balance_after=10.0,
            )
        )
        session.add(
            X402SettlementRecord(
                settlement_key="tx:eip155:8453:0xhistory",
                payment_id="pay_hist",
                user_id=user_id,
                tx_hash="0xhistory",
                network="eip155:8453",
                asset="USDC",
                amount_usd=0.05,
                success=True,
            )
        )
        session.commit()

    resp = client.get("/v1/account/billing-history", headers=_auth_headers(issued["plaintext"]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    txs = data["transactions"]
    assert len(txs) == 2
    x402 = next(t for t in txs if t["type"] == "x402")
    assert x402["tx_hash"] == "0xhistory"
    assert x402["amount_usd"] == pytest.approx(0.05)
    assert x402["status"] == "settled"
    assert data["total_spent"] == pytest.approx(0.05)


# ── 11. Account balance ───────────────────────────────────────────────────


def test_account_balance(db, client: TestClient) -> None:
    from pry.core.db.models_billing import Balance, X402PaymentRecord
    from pry.core.db.session import get_session

    issued = _signup(db, user_id="cust_balance")
    user_id = issued["user_id"]

    with get_session() as session:
        session.add(Balance(user_id=user_id, balance_usd=12.5))
        session.add(
            X402PaymentRecord(
                payment_id="pay_bal",
                tx_hash="0xbal",
                network="eip155:8453",
                asset="USDC",
                amount_usd=1.25,
                verified=True,
                caller_key=user_id,
                user_id=user_id,
            )
        )
        session.commit()

    resp = client.get("/v1/account/balance", headers=_auth_headers(issued["plaintext"]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["balance_usd"] == pytest.approx(12.5)
    assert data["balance_by_chain"]["evm"] == pytest.approx(1.25)
    assert data["balance_by_chain"]["solana"] == 0.0
    assert data["balance_by_chain"]["tron"] == 0.0


# ── 12. x402 payment record carries user_id from caller_key ───────────────


def test_x402_payment_record_has_user_id(db) -> None:
    from pry.core.db.models_billing import X402PaymentRecord
    from pry.core.db.session import get_session
    from pry.payments.x402.ledger_store import record_payment

    record_payment(
        {
            "payment_id": "pay_attr",
            "tx_hash": "0xattr",
            "network": "eip155:8453",
            "asset": "USDC",
            "amount_usd": 0.01,
            "verified": True,
            "caller_key": "pry_attr_00000000000000000000000000000000",
        }
    )

    with get_session() as session:
        row = session.query(X402PaymentRecord).filter_by(payment_id="pay_attr").first()
        assert row is not None
        # user_id is populated from caller_key when no explicit user_id given.
        assert row.user_id == "pry_attr_00000000000000000000000000000000"
        assert row.verified is True


# ── Sanity: the frozen clock helper stays importable for future tests ─────


def test_journey_smoke_timestamps() -> None:
    """The journey runs against a live clock; assert UTC now is sane."""
    now = datetime.now(UTC)
    assert now.tzinfo is UTC
    assert now.year >= 2026
