# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for referral/affiliate system."""

from collections.abc import Iterator

import pytest

from pry.commerce.referrals import PROVIDER_CATALOG, ReferralTracker
from pry.payments.x402 import X402_PRICING, X402Handler


@pytest.fixture(autouse=True)
def _referral_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Use in-memory SQLite for all referral tests."""
    monkeypatch.setenv("PRY_DATABASE_URL", "sqlite://")
    import pry.core.db as _db

    _db._engine = None
    _db._SessionLocal = None
    _db.get_engine()
    # get_engine() no longer creates the schema (Alembic owns it).
    from pry.core.db import Base

    Base.metadata.create_all(_db.get_engine())
    yield
    _db._engine = None
    _db._SessionLocal = None


def test_catalog_completeness() -> None:
    """We have a good catalog of providers."""
    total = sum(len(v) for v in PROVIDER_CATALOG.values())
    assert total >= 50, f"Expected 50+ providers, got {total}"


def test_catalog_categories() -> None:
    assert "llm" in PROVIDER_CATALOG
    assert "hosting" in PROVIDER_CATALOG
    assert "email" in PROVIDER_CATALOG
    assert "monitoring" in PROVIDER_CATALOG


def test_provider_format() -> None:
    for cat, providers in PROVIDER_CATALOG.items():
        for p in providers:
            assert "name" in p, f"Provider in {cat} missing name"
            assert "url" in p, f"Provider in {cat} missing url"
            is_open_source = (
                "open source" in str(p.get("commission", "")).lower()
                or "no affiliate" in str(p.get("note", "")).lower()
            )
            if is_open_source:
                continue
            assert (
                "pry" in p["url"].lower()
                or "ref" in p["url"].lower()
                or "affiliate" in p["url"].lower()
            ), f"Provider {p['name']} URL missing referral: {p['url']}"


def test_referral_click() -> None:
    """Record a click and verify it exists in the database."""
    from pry.core.db import ReferralClick, session_scope

    rt = ReferralTracker()
    click_id = rt.record_click(
        "openai", "https://platform.openai.com/signup?via=pry", source="test"
    )
    assert click_id is not None
    with session_scope() as s:
        click = s.query(ReferralClick).filter_by(click_id=click_id).first()
        assert click is not None
        assert click.provider == "openai"
        assert click.source == "test"
        assert click.converted is False


def test_referral_conversion() -> None:
    """Record a click, convert it, and verify both tables."""
    from pry.core.db import ReferralClick, ReferralConversion, session_scope

    rt = ReferralTracker()
    click_id = rt.record_click("anthropic", "https://console.anthropic.com/?ref=pry")
    success = rt.record_conversion(click_id, revenue_usd=50.0, notes="Annual plan")
    assert success is True
    with session_scope() as s:
        click = s.query(ReferralClick).filter_by(click_id=click_id).first()
        assert click is not None  # ensure click exists
        assert click.converted is True
        assert click.conversion_value_usd == 50.0
        conv = s.query(ReferralConversion).filter_by(click_id=click_id).first()
        assert conv is not None
        assert conv.revenue_usd == 50.0
        assert conv.notes == "Annual plan"


def test_referral_missing_click_conversion() -> None:
    """Converting a non-existent click returns False."""
    rt = ReferralTracker()
    success = rt.record_conversion("nonexistent_click_id")
    assert success is False


def test_referral_stats() -> None:
    """Record a click + conversion and verify stats."""
    rt = ReferralTracker()
    click_id = rt.record_click("openai", "https://platform.openai.com/signup?via=pry")
    rt.record_conversion(click_id, revenue_usd=100.0)
    stats = rt.get_stats(days_back=1)
    assert stats["total_clicks"] >= 1
    assert stats["total_conversions"] >= 1
    assert stats["total_revenue_usd"] >= 100.0
    assert stats["clicks_by_provider"].get("openai", 0) >= 1
    assert stats["conversions_by_provider"].get("openai", 0) >= 1
    assert stats["revenue_by_provider_usd"].get("openai", 0.0) >= 100.0
    assert 0 < stats["conversion_rate"] <= 1.0
    assert stats["period_days"] == 1
    assert stats["catalog_size"] >= 50


def test_referral_stats_empty() -> None:
    """Stats with no data returns zeroes."""
    rt = ReferralTracker()
    stats = rt.get_stats(days_back=1)
    assert stats["total_clicks"] == 0
    assert stats["total_conversions"] == 0
    assert stats["total_revenue_usd"] == 0.0
    assert stats["conversion_rate"] == 0.0


def test_referral_in_app_usage() -> None:
    """Track in-app usage revenue and verify in database."""
    from pry.core.db import ReferralInAppUsage, session_scope

    rt = ReferralTracker()
    rt.track_in_app_usage("openai", 15.0)
    with session_scope() as s:
        usage = s.query(ReferralInAppUsage).filter_by(provider="openai").first()
        assert usage is not None
        assert usage.revenue_usd == 15.0


def test_referral_catalog() -> None:
    """Verify get_catalog returns correct data."""
    rt = ReferralTracker()
    full = rt.get_catalog()
    assert len(full) > 0
    for entry in full:
        assert "category" in entry
        assert "providers" in entry
    llm = rt.get_catalog("llm")
    assert len(llm) > 0
    assert llm[0]["name"] == "OpenAI"
    empty = rt.get_catalog("nonexistent")
    assert empty == []


# ── x402 tests (unchanged) ────────────────────────────────────────


def test_x402_payment_request() -> None:
    h = X402Handler()
    body, headers = h.create_payment_required("scrape", "https://example.com/scrape")
    assert body["x402Version"] == 1
    assert "accepts" in body
    base_accept = next(a for a in body["accepts"] if a["network"] == "base")
    assert base_accept["maxAmountRequired"] == "1000"
    assert base_accept["asset"] == "USDC"
    assert "PAYMENT-REQUIRED" in headers


def test_x402_require_payment() -> None:
    h = X402Handler()
    resp = h.require_payment("crawl")
    assert resp["status_code"] == 402
    assert "PAYMENT-REQUIRED" in resp["headers"]
    assert "accepts" in resp["body"]


def test_x402_pricing() -> None:
    assert "scrape" in X402_PRICING
    assert "crawl" in X402_PRICING
    assert "llm_call" in X402_PRICING
    for _op, info in X402_PRICING.items():
        assert info["price_usd"] > 0
        assert "description" in info


def test_x402_stats() -> None:
    h = X402Handler()
    stats = h.get_stats()
    assert "total_payments" in stats
    assert "wallet" in stats
    assert "pricing" in stats
