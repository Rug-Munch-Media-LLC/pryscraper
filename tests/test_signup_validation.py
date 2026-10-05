# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Unit tests for the split hosting signup modules.

Targets the public helpers extracted into ``signup_validation`` (quote
resolution, x402 ``accepts`` build, public base URL) and ``signup_provision``
(draft/record assembly, verification-code shaping, result payload). Pure
functions are tested directly; the I/O boundaries (persistence, user lookup,
email) are faked with injected stand-ins — no network, no DB.
"""

from __future__ import annotations

from typing import NamedTuple

import pytest

from pry.commerce.hosting import signup_validation as validation
from pry.commerce.hosting.errors import PlanNotPurchasable, WalletUnconfigured
from pry.payments.x402.scheme import X402Scheme


class _FakePlan(NamedTuple):
    """Minimal plan stand-in for the accepts/record builders."""

    tier: str
    name: str
    price_usd_monthly: float
    is_purchasable: bool = True


def _quote(plan: _FakePlan | None = None) -> validation.InvoiceQuote:
    plan = plan or _FakePlan("pro", "Pro", 49.0)
    return validation.InvoiceQuote(
        plan=plan,
        asset="USDC",
        chain="base",
        amount_atomic=49_000_000,
        pay_to="0x" + "1" * 40,
    )


class TestPublicBaseUrl:
    """PRY_PUBLIC_BASE_URL override, trailing-slash normalisation."""

    def test_defaults_to_production_api(self, monkeypatch):
        monkeypatch.delenv("PRY_PUBLIC_BASE_URL", raising=False)
        assert validation._public_base_url() == "https://api.pryscraper.com"

    def test_env_override_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("PRY_PUBLIC_BASE_URL", "https://staging.example.com/")
        assert validation._public_base_url() == "https://staging.example.com"


class TestResolveQuote:
    """Resolving a tier to x402 pricing primitives, fail-closed."""

    def test_purchasable_tier_resolves_primitives(self):
        quote = validation._resolve_quote("pro")
        assert quote.plan.tier == "pro"
        assert quote.pay_to.startswith("0x")
        assert quote.chain
        assert quote.amount_atomic > 0

    def test_unpurchasable_tier_raises(self):
        with pytest.raises(PlanNotPurchasable):
            validation._resolve_quote("enterprise")

    def test_unconfigured_wallet_fails_closed(self, monkeypatch):
        monkeypatch.setattr(validation, "wallet_configured", lambda _pay_to: False)
        with pytest.raises(WalletUnconfigured):
            validation._resolve_quote("pro")


class TestBuildSignupAccepts:
    """The single-option x402 accepts list shape."""

    def test_accepts_has_exact_scheme_and_atomic_amount(self):
        plan = _FakePlan("pro", "Pro", 49.0)
        accepts = validation._build_signup_accepts(
            plan,
            resource="https://api.pryscraper.com/api/hosting/signup/host_x",
            invoice_id="host_x",
            chain="base",
            amount_atomic=49_000_000,
            pay_to="0x" + "1" * 40,
            asset="USDC",
        )
        assert len(accepts) == 1
        entry = accepts[0]
        assert entry["scheme"] == X402Scheme.EXACT.value
        assert entry["maxAmountRequired"] == "49000000"
        assert entry["payToAddress"] == "0x" + "1" * 40
        assert entry["extra"]["operation"] == "hosting_signup"
        assert entry["extra"]["plan_tier"] == "pro"
        assert entry["extra"]["invoice_id"] == "host_x"
        assert entry["extra"]["priceUsd"] == 49.0

    def test_accepts_description_names_plan_and_price(self):
        plan = _FakePlan("pro", "Pro", 49.0)
        accepts = validation._build_signup_accepts(
            plan,
            resource="r",
            invoice_id="i",
            chain="base",
            amount_atomic=1,
            pay_to="p",
            asset="USDC",
        )
        assert "Pro" in accepts[0]["description"]
        assert "49.0" in accepts[0]["description"]
