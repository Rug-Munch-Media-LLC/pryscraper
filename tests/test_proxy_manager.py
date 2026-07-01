"""Tests for proxy manager with affiliate signup flow."""

import pytest

from proxy_manager import (
    FREE_PROXY_SOURCES,
    PREMIUM_PROXY_PROVIDERS,
    ProxyConfig,
    ProxyManager,
)


@pytest.fixture
def pm(tmp_path):
    """ProxyManager with isolated data dir so tests don't pollute ~/.pry."""
    return ProxyManager(data_dir=tmp_path)


def test_free_proxy_sources_exist() -> None:
    assert len(FREE_PROXY_SOURCES) >= 1
    for p in FREE_PROXY_SOURCES:
        assert "name" in p
        assert "url" in p
        assert "cost" in p


def test_premium_providers_have_affiliates() -> None:
    assert len(PREMIUM_PROXY_PROVIDERS) >= 5
    for p in PREMIUM_PROXY_PROVIDERS:
        assert "name" in p
        assert "signup_url" in p
        assert (
            "pry" in p["signup_url"].lower()
            or "ref" in p["signup_url"].lower()
            or "aff" in p["signup_url"].lower()
        )
        assert "commission" in p


def test_proxy_manager_init(pm: ProxyManager) -> None:
    assert pm.active_config is not None
    assert pm.active_config.provider == "free"


def test_get_signup_link(pm: ProxyManager) -> None:
    url = pm.get_signup_link("brightdata")
    assert "pry" in url.lower() or "ref" in url.lower()
    url2 = pm.get_signup_link()
    assert len(url2) > 0


def test_needs_premium_detection(pm: ProxyManager) -> None:
    assert pm.needs_premium_proxy("Cloudflare challenge detected") is True
    assert pm.needs_premium_proxy("429 Too Many Requests") is True
    assert pm.needs_premium_proxy("") is False
    assert pm.needs_premium_proxy("normal connection error") is False


def test_list_providers(pm: ProxyManager) -> None:
    providers = pm.list_providers()
    assert "free" in providers
    assert "premium" in providers
    assert len(providers["premium"]) >= 5


def test_select_provider_without_credentials(pm: ProxyManager) -> None:
    result = pm.select_provider("brightdata")
    assert result["success"] is False
    assert result.get("needs_signup") is True
    assert "signup_url" in result


def test_select_provider_with_credentials(pm: ProxyManager) -> None:
    creds = {
        "username": "test_user",
        "password": "test_pass",
        "proxy_url": "gate.brightdata.com:8000",
    }
    result = pm.select_provider("brightdata", creds)
    assert result["success"] is True
    assert pm.active_config.provider == "brightdata"


def test_get_recommendation(pm: ProxyManager) -> None:
    rec = pm.get_recommendation("normal error")
    assert rec["needs_premium"] is False
    rec2 = pm.get_recommendation("Cloudflare challenge detected")
    assert rec2["needs_premium"] is True
    assert "signup_url" in rec2
    assert "pry" in rec2["signup_url"].lower() or "ref" in rec2["signup_url"].lower()


def test_proxy_config_dataclass() -> None:
    c = ProxyConfig(
        provider="brightdata",
        proxy_url="gate.brightdata.com:8000",
        username="user",
        password="pass",
        proxy_type="http",
    )
    assert c.provider == "brightdata"
    assert c.auto_rotate is True


def test_record_referral_click(pm: ProxyManager) -> None:
    click_id = pm.record_referral_click("smartproxy", user_id="test_user")
    assert click_id != ""
    assert len(click_id) > 0


def test_recent_clicks(pm: ProxyManager) -> None:
    clicks = pm.get_recent_clicks(days_back=7)
    assert isinstance(clicks, list)
