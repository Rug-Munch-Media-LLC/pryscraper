# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hosting plan catalog and signup preconditions."""

from __future__ import annotations

import pytest

import pry.commerce.hosting as hosting_mod
from pry.commerce.hosting import (
    WalletUnconfigured,
    create_hosting_signup,
    list_plans,
)
from tests.hosting_assertions import assert_pro_plan, assert_team_and_enterprise_plans
from tests.hosting_support import (  # noqa: F401
    _REAL_WALLET,
    _clean_hosting_state,
)


# ── Plans ───────────────────────────────────────────────────────────────────
def test_plan_catalog_matches_tiers() -> None:
    plans = {p["tier"]: p for p in list_plans()}
    assert_pro_plan(plans)
    assert_team_and_enterprise_plans(plans)


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
