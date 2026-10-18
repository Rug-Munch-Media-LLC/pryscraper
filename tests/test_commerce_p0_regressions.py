# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""P0 commerce regressions: email verification, paid upgrades, quota auth.

Three real defects, each pinned here:

(a) A mail-configured signup stored ``""`` as the verification code, so
    ``compare_digest("", code)`` could never pass — no such signup could ever
    confirm. The stored code must be exactly the emailed code.
(b) ``change-tier`` activated the new tier with no payment (free upgrade).
    It must answer 402 with a prorated invoice and keep the current tier.
(c) ``PRY_BILLING_KEYS`` tiers were neither authenticated nor enforced; an
    over-quota key must now be rejected with 429 by the HTTP middleware.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import pry.commerce.hosting as hosting_mod
from pry.api.routers.commerce.billing_subscription import renewals
from pry.api.routers.commerce.billing_subscription.models import (
    SubscriptionChangeTierRequest,
)
from pry.api.routers.commerce.billing_subscription.state import (
    _TIER_CHANGE_INVOICES,
)
from pry.commerce.billing import (
    activate_subscription,
    reset_subscription_state,
    subscription_status,
)
from pry.commerce.hosting import (
    create_hosting_signup,
    verify_hosting_email,
)
from pry.core import middleware as mw
from pry.core.db import models as models_mod
from pry.core.db.session import session_scope
from pry.core.middleware import PryHttpMiddleware

_REAL_WALLET = "0x00000000000000000000000000000000000ABCDE"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test (same pattern as the hosting suites)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/p0.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)

    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path}/p0.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _wallet(monkeypatch):
    monkeypatch.delenv("PRY_HOSTING_SKIP_EMAIL_VERIFY", raising=False)
    monkeypatch.setattr(hosting_mod, "X402_NETWORK_WALLETS", {"eip155:8453": _REAL_WALLET})
    monkeypatch.setattr(hosting_mod, "X402_WALLET", _REAL_WALLET)


# ── (a) stored code == emailed code, and that code confirms ──
def test_emailed_code_is_stored_and_confirms(db, monkeypatch) -> None:
    import pry.commerce.hosting.checkout as checkout

    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(checkout, "mail_configured", lambda: True)
    monkeypatch.setattr(
        checkout,
        "send_hosting_verification_email",
        lambda **kw: sent.append(kw),
    )

    response = create_hosting_signup("verify-me@example.com", "pro")

    assert len(sent) == 1
    emailed = sent[0]["code"]
    assert emailed
    # Delivered -> the code must NOT be echoed in the API response.
    assert response["verification_code"] is None
    assert response["email_delivery"] == "sent"

    with session_scope() as session:
        row = (
            session.query(models_mod.HostingInvoice)
            .filter_by(invoice_id=response["invoice_id"])
            .one()
        )
        assert row.verification_code == emailed, "stored code must be the emailed code"

    assert verify_hosting_email(response["invoice_id"], emailed)["verified"] is True


def test_five_wrong_attempts_lock_verification(db, monkeypatch) -> None:
    import pry.commerce.hosting.checkout as checkout

    monkeypatch.setattr(checkout, "mail_configured", lambda: False)
    response = create_hosting_signup("lock-me@example.com", "pro")
    code = response["verification_code"]
    assert code

    for _ in range(5):
        assert verify_hosting_email(response["invoice_id"], "000000")["verified"] is False
    locked = verify_hosting_email(response["invoice_id"], code)
    assert locked["verified"] is False
    assert locked.get("locked") is True


# ── (b) upgrade requires payment; repeat reuses the invoice ──
@pytest.fixture
def upgrade_calls(monkeypatch):
    reset_subscription_state()
    _TIER_CHANGE_INVOICES.clear()
    activate_subscription("sk_upgrade", "pro", 1)
    calls: list[dict[str, Any]] = []

    def _fake_invoice(tier: str, api_key: str, months: int = 1, **kwargs: Any) -> dict[str, Any]:
        calls.append({"tier": tier, "months": months, **kwargs})
        return {
            "invoice_id": f"inv_tier_{len(calls)}",
            "tier": tier,
            "amount_usd": kwargs.get("amount_override_usd"),
            "amount_asset": "150000000",
            "chain": "base",
            "payment_address": _REAL_WALLET,
            "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
            "payment_method": "x402",
            "asset": "USDC",
        }

    monkeypatch.setattr(renewals, "create_subscription_invoice", _fake_invoice)
    monkeypatch.setattr(renewals, "wallet_configured", lambda _w: True)
    yield calls
    reset_subscription_state()
    _TIER_CHANGE_INVOICES.clear()


def test_upgrade_returns_402_and_keeps_current_tier(upgrade_calls) -> None:
    payload = SubscriptionChangeTierRequest(api_key="sk_upgrade", new_tier="team")
    resp = renewals.billing_subscription_change_tier(payload)

    assert resp.status_code == 402
    detail = json.loads(resp.body)
    assert detail["invoice_required"] is True
    assert detail["invoice_id"]
    assert detail["amount"] == 150.0  # team 199 - pro 49, one month remaining
    assert detail["asset"] == "USDC"
    assert detail["chain"] == "base"
    assert detail["pay_to"] == _REAL_WALLET
    # No free upgrade: the tier is unchanged until the invoice is paid.
    assert subscription_status("sk_upgrade")["tier"] == "pro"
    assert upgrade_calls[0]["amount_override_usd"] == 150.0


def test_repeated_upgrade_reuses_the_same_invoice(upgrade_calls) -> None:
    payload = SubscriptionChangeTierRequest(api_key="sk_upgrade", new_tier="team")
    first = renewals.billing_subscription_change_tier(payload)
    second = renewals.billing_subscription_change_tier(payload)

    assert first.status_code == second.status_code == 402
    assert json.loads(first.body)["invoice_id"] == json.loads(second.body)["invoice_id"]
    assert len(upgrade_calls) == 1, "repeat must not mint a second invoice"


# ── (c) over-quota subscription key -> 429 from the middleware ──
class _DenyingEnforcer:
    def check_request(self, api_key: str | None) -> bool:
        return False


def test_over_quota_billing_key_gets_429(monkeypatch) -> None:
    sent: list[dict[str, Any]] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    async def app(scope, receive, send):  # pragma: no cover - must not run
        raise AssertionError("downstream must not see a denied request")

    def _authorize(scope):
        scope["pry_api_key"] = {
            "key_id": "sk_env_pro",
            "user_id": "billing:sk_env_p",
            "name": "billing-key",
            "scopes": ["scrape"],
            "tier": "ENTERPRISE",
            "billing_env": True,
        }
        return True

    monkeypatch.setattr(mw, "request_authorized", _authorize)
    monkeypatch.setattr(mw, "_path_exists", lambda _p, _a: True)
    monkeypatch.setattr(mw, "billing_enforcer", lambda: _DenyingEnforcer())

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/scrape",
        "headers": [(b"authorization", b"Bearer sk_env_pro")],
        "client": ("203.0.113.9", 5),
        "query_string": b"",
    }
    asyncio.run(PryHttpMiddleware(app)(scope, receive, send))

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 429
    body = json.loads(sent[1]["body"])
    assert body["code"] == "rate_limit_exceeded"
