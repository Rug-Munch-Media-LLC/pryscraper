# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hosting route-level behaviour (manifest, confirm, instances)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import pry.commerce.hosting as hosting_mod
from pry.commerce.hosting import (
    InstanceNotFound,
    cancel_instance,
    confirm_hosting_payment_sync,
    get_instance,
    list_plans,
    renew_instance,
)
from tests.hosting_assertions import assert_instance_scoped_reads

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

from tests.hosting_support import (  # noqa: F401
    _REAL_WALLET,
    _clean_hosting_state,
    _FakeFacilitator,
    _provision,
    _unverified_result,
    _verified_result,
    client,
    db,
)


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
    assert_instance_scoped_reads(client, headers, instance_id)

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
