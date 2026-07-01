"""Tests for referral/affiliate system."""

from referrals import PROVIDER_CATALOG, ReferralTracker
from x402 import X402_PRICING, X402Handler


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
            is_open_source = "open source" in str(p.get("commission", "")).lower() or "no affiliate" in str(p.get("note", "")).lower()
            if is_open_source:
                continue
            assert "pry" in p["url"].lower() or "ref" in p["url"].lower() or "affiliate" in p["url"].lower(), f"Provider {p['name']} URL missing referral: {p['url']}"


def test_referral_click() -> None:
    rt = ReferralTracker()
    click_id = rt.record_click("openai", "https://platform.openai.com/signup?via=pry", source="test")
    assert click_id is not None
    assert any(c["id"] == click_id for c in rt.clicks)


def test_referral_conversion() -> None:
    rt = ReferralTracker()
    click_id = rt.record_click("anthropic", "https://console.anthropic.com/?ref=pry")
    success = rt.record_conversion(click_id, revenue_usd=50.0, notes="Annual plan")
    assert success is True


def test_referral_stats() -> None:
    rt = ReferralTracker()
    click_id = rt.record_click("openai", "https://platform.openai.com/signup?via=pry")
    rt.record_conversion(click_id, revenue_usd=100.0)
    stats = rt.get_stats(days_back=1)
    assert stats["total_clicks"] >= 1
    assert stats["total_revenue_usd"] >= 100.0


def test_x402_payment_request() -> None:
    h = X402Handler()
    body, headers = h.create_payment_required("scrape", "https://example.com/scrape")
    assert body["x402Version"] == 1
    assert "accepts" in body
    base_accept = next(a for a in body["accepts"] if a["network"] == "base")
    assert base_accept["maxAmountRequired"] == "1000"  # $0.001 = 1000 USDC units
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
