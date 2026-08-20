# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for proxy manager with affiliate signup flow."""

import json
import time

import pytest

from proxy_manager import (
    FREE_PROXY_SOURCES,
    PREMIUM_PROXY_PROVIDERS,
    ProxyConfig,
    ProxyManager,
)
from webshare_proxy import WEBSHARE_PROXY_LIST_ENV, clear_cache

_WS_SAMPLE = (
    "http://user:pass@10.0.0.1:8080 http://user:pass@10.0.0.2:8080 http://user:pass@10.0.0.3:8080"
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


# ── Health-aware proxy selection ─────────────────────────────────


def _two_proxy_pool(pm: ProxyManager, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Point _candidate_proxies at a fixed 2-proxy pool for unit tests."""
    pool = ["http://p1:8080", "http://p2:8080"]
    monkeypatch.setattr(pm, "_candidate_proxies", lambda: list(pool))
    return pool


def test_health_scoring_ranks_fast_proxy_higher(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_proxy_pool(pm, monkeypatch)
    pm.record_proxy_result("http://p1:8080", True, 0.2)
    pm.record_proxy_result("http://p1:8080", True, 0.3)
    pm.record_proxy_result("http://p2:8080", True, 5.0)

    assert pm.get_best_proxy() == "http://p1:8080"
    s1 = pm.proxy_health_summary("http://p1:8080")
    s2 = pm.proxy_health_summary("http://p2:8080")
    assert s1["known"] is True
    assert s1["success_rate"] == 1.0
    assert s1["avg_latency"] < s2["avg_latency"]


def test_unknown_proxy_is_neutral_and_returned_when_only_option(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pm, "_candidate_proxies", lambda: ["http://only:8080"])
    assert pm.get_best_proxy() == "http://only:8080"
    # No health data yet -> neutral score, not dead.
    assert pm.proxy_health_summary("http://only:8080")["known"] is False


def test_rotation_on_failure_selects_healthy_proxy(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_proxy_pool(pm, monkeypatch)
    # p1 trips the circuit breaker after N consecutive failures.
    for _ in range(pm.consecutive_failure_threshold):
        pm.record_proxy_result("http://p1:8080", False, 2.0)

    assert pm.proxy_health_summary("http://p1:8080")["in_cooldown"] is True
    # Rotates to the next healthy proxy.
    assert pm.get_best_proxy() == "http://p2:8080"
    assert pm.get_proxy_url() == "http://p2:8080"


def test_single_failure_does_not_trip_circuit_breaker(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_proxy_pool(pm, monkeypatch)
    pm.record_proxy_result("http://p1:8080", False, 2.0)
    # One failure < threshold: proxy stays selectable (scored lower).
    assert pm.proxy_health_summary("http://p1:8080")["in_cooldown"] is False
    assert pm.get_best_proxy() in {"http://p1:8080", "http://p2:8080"}


def test_get_proxy_url_returns_none_when_all_proxies_tripped(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_proxy_pool(pm, monkeypatch)
    for p in ("http://p1:8080", "http://p2:8080"):
        for _ in range(pm.consecutive_failure_threshold):
            pm.record_proxy_result(p, False, 2.0)
    # Never return a dead/cooldown proxy — fall back to the next tier.
    assert pm.get_proxy_url() is None
    assert pm.get_best_proxy("example.com") is None


def test_cooldown_expires_and_proxy_recovers(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pm, "_candidate_proxies", lambda: ["http://p1:8080"])
    for _ in range(pm.consecutive_failure_threshold):
        pm.record_proxy_result("http://p1:8080", False, 1.0)
    assert pm.get_proxy_url() is None

    # Rewind the cooldown timestamp -> proxy is selectable again.
    pm._health_data["proxies"]["http://p1:8080"]["cooldown_until"] = time.time() - 1
    assert pm.proxy_health_summary("http://p1:8080")["in_cooldown"] is False
    assert pm.get_proxy_url() == "http://p1:8080"


def test_success_resets_consecutive_failure_counter(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_proxy_pool(pm, monkeypatch)
    pm.record_proxy_result("http://p1:8080", False, 1.0)
    pm.record_proxy_result("http://p1:8080", False, 1.0)
    pm.record_proxy_result("http://p1:8080", True, 0.5)  # recovery
    pm.record_proxy_result("http://p1:8080", False, 1.0)
    summary = pm.proxy_health_summary("http://p1:8080")
    assert summary["consecutive_failures"] == 1
    assert summary["in_cooldown"] is False


def test_per_domain_affinity_prefers_winning_proxy(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_proxy_pool(pm, monkeypatch)
    # p2 wins for example.com; p1 is healthier overall.
    pm.record_proxy_result("http://p2:8080", True, 1.0, domain="https://www.example.com/some/path")
    pm.record_proxy_result("http://p1:8080", True, 0.1)
    pm.record_proxy_result("http://p1:8080", True, 0.1)

    # For the known domain, the winning proxy is preferred.
    assert pm.get_best_proxy("example.com") == "http://p2:8080"
    # Without domain context, health wins.
    assert pm.get_best_proxy() == "http://p1:8080"


def test_affinity_failure_erodes_wins(pm: ProxyManager, monkeypatch: pytest.MonkeyPatch) -> None:
    _two_proxy_pool(pm, monkeypatch)
    pm.record_proxy_result("http://p1:8080", True, 0.5, domain="example.com")
    pm.record_proxy_result("http://p1:8080", True, 0.5, domain="example.com")
    pm.record_proxy_result("http://p2:8080", True, 0.3)
    pm.record_proxy_result("http://p1:8080", False, 2.0, domain="example.com")
    pm.record_proxy_result("http://p1:8080", False, 2.0, domain="example.com")
    # Wins eroded to 0 -> p1 is no longer preferred for that domain.
    aff = pm._health_data["affinity"]["example.com"]
    assert aff["http://p1:8080"] == 0
    # Selector falls back to the healthiest proxy (p2).
    assert pm.get_best_proxy("example.com") == "http://p2:8080"


def test_domain_normalization_strips_scheme_path_port(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_proxy_pool(pm, monkeypatch)
    pm.record_proxy_result("http://p1:8080", True, 0.5, domain="HTTPS://www.Example.com:443/x")
    pm.record_proxy_result("http://p1:8080", True, 0.5, domain="example.com")
    assert pm.get_best_proxy("example.com") == "http://p1:8080"


def test_health_persists_to_data_dir_json(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(WEBSHARE_PROXY_LIST_ENV, raising=False)
    pm.record_proxy_result("http://p1:8080", True, 0.5, domain="example.com")

    health_file = pm.data_dir / "proxy_health.json"
    assert health_file.exists()
    data = json.loads(health_file.read_text())
    assert "http://p1:8080" in data["proxies"]
    assert data["affinity"]["example.com"]["http://p1:8080"] == 1

    # A fresh instance reloads the same state.
    pm2 = ProxyManager(data_dir=pm.data_dir)
    summary = pm2.proxy_health_summary("http://p1:8080")
    assert summary["known"] is True
    assert summary["success_rate"] == 1.0


def test_health_rolling_window_caps_samples(pm: ProxyManager) -> None:
    pm.health_window_size = 5
    for _ in range(10):
        pm.record_proxy_result("http://p1:8080", True, 0.1)
    assert pm.proxy_health_summary("http://p1:8080")["samples"] == 5


def test_webshare_pool_healthiest_selection(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv(WEBSHARE_PROXY_LIST_ENV, _WS_SAMPLE)
    clear_cache()
    pm = ProxyManager(data_dir=tmp_path)
    assert pm.active_config.provider == "webshare"
    # Fresh pool -> first configured proxy.
    assert pm.get_proxy_url() == "http://user:pass@10.0.0.1:8080"
    # p1 dies -> rotate to the next healthy pool member.
    for _ in range(pm.consecutive_failure_threshold):
        pm.record_proxy_result("http://user:pass@10.0.0.1:8080", False, 1.0)
    assert pm.get_proxy_url() == "http://user:pass@10.0.0.2:8080"
    clear_cache()


# ── needs_premium_proxy classification ──────────────────────────


def test_needs_premium_detection_extended(pm: ProxyManager) -> None:
    # Block / anti-bot signatures -> premium recommended.
    assert pm.needs_premium_proxy("Cloudflare: Attention Required!") is True
    assert pm.needs_premium_proxy("captcha required") is True
    assert pm.needs_premium_proxy("403 Forbidden") is True
    assert pm.needs_premium_proxy("Datadome challenge") is True
    # Timeout is treated as a block/rate-limit signal.
    assert pm.needs_premium_proxy("The read operation timed out") is True
    # Generic connectivity failures -> premium NOT recommended.
    assert pm.needs_premium_proxy("Connection refused by remote host") is False
    assert pm.needs_premium_proxy("DNS resolution failed for example.com") is False
    assert pm.needs_premium_proxy("Connection reset by peer") is False
    assert pm.needs_premium_proxy("502 Bad Gateway from upstream") is False
    # Explicit block signature beats a generic signal in the same message.
    assert pm.needs_premium_proxy("Cloudflare: connection reset") is True


# ── test_proxy with mocked HTTP ─────────────────────────────────


def test_test_proxy_mocked_success(pm: ProxyManager, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    class _FakeResponse:
        is_success = True
        text = '{"ip": "203.0.113.7"}'
        status_code = 200

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *exc) -> None:
            return None

        def get(self, url: str) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    result = pm.test_proxy("http://p1:8080")
    assert result["working"] is True
    assert result["status"] == 200
    assert "203.0.113.7" in result["ip"]
    assert isinstance(result["latency"], float)


def test_test_proxy_mocked_network_failure(
    pm: ProxyManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    class _FailingClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "_FailingClient":
            return self

        def __exit__(self, *exc) -> None:
            return None

        def get(self, url: str) -> None:
            raise httpx.ConnectError("proxy unreachable")

    monkeypatch.setattr(httpx, "Client", _FailingClient)
    result = pm.test_proxy("http://p1:8080")
    assert result["working"] is False
    assert "error" in result
