# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hosting payment confirmation, provisioning and lifecycle."""

from __future__ import annotations

import pytest

import pry.commerce.hosting as hosting_mod
from pry.commerce import billing_service
from pry.commerce.hosting import (
    InstanceNotFound,
    cancel_instance,
    confirm_hosting_payment_sync,
    create_hosting_signup,
    get_instance,
    list_instances,
    renew_instance,
    suspend_instance,
)
from tests.hosting_assertions import (
    assert_instance_provisioned,
    assert_key_reference_only,
    assert_renewal_invoice,
)
from tests.hosting_support import (  # noqa: F401
    _REAL_WALLET,
    _clean_hosting_state,
    _FakeFacilitator,
    _provision,
    _unverified_result,
    _verified_result,
    db,
)


def test_confirm_provisions_instance_and_mints_key(db, monkeypatch) -> None:
    monkeypatch.setattr(
        hosting_mod, "_get_self_facilitator", lambda: _FakeFacilitator(_verified_result())
    )
    invoice = create_hosting_signup("buyer@example.com", "pro")
    result = confirm_hosting_payment_sync(invoice["invoice_id"], "0xdeadbeef")

    assert_instance_provisioned(result)
    assert_key_reference_only(result)
    instance = result["instance"]

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


def test_get_and_list_instances(db, monkeypatch) -> None:
    result = _provision(db, monkeypatch, email="list@example.com", tier="team")
    instance = result["instance"]
    detail = get_instance(instance["instance_id"])
    assert detail["instance_id"] == instance["instance_id"]
    assert detail["active"] is True
    assert detail["plan_tier"] == "team"

    listed = list_instances(instance["user_id"])
    expected = [instance["instance_id"]]
    assert [i["instance_id"] for i in listed] == expected

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
    assert_renewal_invoice(renewal, instance_id)

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
