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

from typing import Any, NamedTuple

import pytest

from pry.commerce.hosting import signup_provision as provision, signup_validation as validation
from pry.commerce.hosting.errors import PlanNotPurchasable, WalletUnconfigured
from pry.commerce.hosting.plans import get_plan
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


class TestBuildSignupDraft:
    """Draft assembly: invoice id, resource URL and x402 body."""

    def test_draft_resource_points_at_public_base(self, monkeypatch):
        monkeypatch.setenv("PRY_PUBLIC_BASE_URL", "https://pay.example.com")
        draft = provision._build_signup_draft(_quote())
        assert draft.invoice_id.startswith("host_")
        assert draft.resource == (f"https://pay.example.com/api/hosting/signup/{draft.invoice_id}")
        # The resource URL is carried inside the accepts entry, not the body
        # root — that is how build_payment_required shapes the manifest.
        assert draft.body["accepts"][0]["resource"] == draft.resource

    def test_draft_body_carries_accepts_and_operation(self):
        draft = provision._build_signup_draft(_quote())
        assert draft.body["accepts"][0]["extra"]["operation"] == "hosting_signup"
        assert draft.body["accepts"][0]["maxAmountRequired"] == "49000000"


class TestNewSignupInvoice:
    """The persisted record: normalisation, expiry, verification fields."""

    def test_record_normalises_email_and_stamps_fields(self, monkeypatch):
        monkeypatch.setattr(provision, "_invoice_ttl_seconds", lambda: 3600)
        draft = provision._build_signup_draft(_quote())
        record = provision._new_signup_invoice(_quote(), "  User@Example.COM ", "u1", draft)

        assert record["user_email"] == "user@example.com"
        assert record["kind"] == "signup"
        assert record["status"] == "pending"
        assert record["payment_method"] == "x402"
        assert record["amount_atomic"] == 49_000_000
        assert record["email_verified"] is False
        assert len(record["verification_code"]) == 6
        assert record["expires_at"]

    def test_record_payment_block_mirrors_quote(self):
        draft = provision._build_signup_draft(_quote())
        quote = _quote()
        record = provision._new_signup_invoice(quote, "a@b.com", "u1", draft)
        assert record["payment"]["network"] == quote.chain
        assert record["payment"]["amount_usd"] == quote.plan.price_usd_monthly
        assert record["payment"]["tx_hash"] is None


class TestSendVerificationEmail:
    """Email is best-effort; the code is exposed only when mail is off."""

    def _record(self) -> dict[str, Any]:
        return {
            "invoice_id": "host_x",
            "user_email": "a@b.com",
            "verification_code": "abc123",
        }

    def test_unconfigured_mail_returns_dev_code(self, monkeypatch):
        import pry.commerce.hosting.checkout as checkout

        monkeypatch.setattr(checkout, "mail_configured", lambda: False)
        sent: list[Any] = []
        monkeypatch.setattr(
            checkout, "send_hosting_verification_email", lambda **kw: sent.append(kw)
        )
        assert provision._send_verification_email(self._record()) == "abc123"
        assert sent == [], "no email should be sent when mail is unconfigured"

    def test_configured_mail_sends_and_returns_none(self, monkeypatch):
        import pry.commerce.hosting.checkout as checkout

        monkeypatch.setattr(checkout, "mail_configured", lambda: True)
        sent: list[dict[str, Any]] = []
        monkeypatch.setattr(
            checkout, "send_hosting_verification_email", lambda **kw: sent.append(kw)
        )
        assert provision._send_verification_email(self._record()) is None
        assert sent, "email should be sent when mail is configured"
        assert sent[0]["to_email"] == "a@b.com"
        assert sent[0]["code"] == "abc123"

    def test_delivery_failure_never_raises(self, monkeypatch):
        import pry.commerce.hosting.checkout as checkout

        def _boom(**_kw):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(checkout, "mail_configured", lambda: True)
        monkeypatch.setattr(checkout, "send_hosting_verification_email", _boom)
        assert provision._send_verification_email(self._record()) is None


class TestSignupResult:
    """The API payload surfaces the x402 body and email-verification state."""

    def test_result_exposes_payment_required_body(self):
        draft = provision._build_signup_draft(_quote())
        record = provision._new_signup_invoice(_quote(), "a@b.com", "u1", draft)
        result = provision._signup_result(_quote(), record, "u1")
        assert result["payment_required"] == record["x402_body"]
        assert result["invoice_id"] == record["invoice_id"]
        assert result["email_verified"] is False
        assert result["verification_code"] == record["verification_code"]

    def test_empty_verification_code_surfaces_as_none(self):
        quote = _quote()
        draft = provision._build_signup_draft(quote)
        record = provision._new_signup_invoice(quote, "a@b.com", "u1", draft)
        record["verification_code"] = ""
        record["email_verified"] = True
        result = provision._signup_result(quote, record, "u1")
        assert result["verification_code"] is None
        assert result["email_verified"] is True


class TestProvisionSignupInvoice:
    """End-to-end orchestration with the I/O boundaries faked."""

    def _patch_io(self, monkeypatch, *, verification_email: bool, mail_ok: bool = True):
        import pry.commerce.hosting.checkout as checkout
        from pry.commerce.hosting import provisioning

        saved: list[dict[str, Any]] = []
        monkeypatch.setattr(provision, "_resolve_quote", lambda tier: _quote())
        monkeypatch.setattr(provision, "_save_invoice", lambda rec: saved.append(rec))
        monkeypatch.setattr(provision, "_invoice_ttl_seconds", lambda: 3600)
        monkeypatch.setattr(provision, "_send_verification_email", lambda rec: "c0ffee")
        monkeypatch.setattr(provision, "_ensure_user_by_email_proxy", None, raising=False)
        monkeypatch.setattr(provisioning, "_ensure_user_by_email", lambda email: "user-1")
        monkeypatch.setattr(checkout, "mail_configured", lambda: mail_ok)
        return saved

    def test_verification_email_path_exposes_code(self, monkeypatch):
        saved = self._patch_io(monkeypatch, verification_email=True)
        result = provision._provision_signup_invoice("a@b.com", "pro", verification_email=True)
        assert saved, "invoice must be persisted"
        assert result["verification_code"] == "c0ffee"
        assert result["email_verified"] is False

    def test_no_verification_path_pre_approves(self, monkeypatch):
        saved = self._patch_io(monkeypatch, verification_email=False)
        result = provision._provision_signup_invoice("a@b.com", "pro", verification_email=False)
        assert saved
        assert result["verification_code"] is None
        assert result["email_verified"] is True
        assert saved[0]["verification_code"] == ""


class TestPlanHelperSanity:
    """Anchor the real plans module so quote math cannot silently drift."""

    def test_real_pro_plan_is_purchasable(self):
        plan = get_plan("pro")
        assert plan.is_purchasable is True
        assert plan.price_usd_monthly > 0
