"""Tests for resilience primitives and their integration into UltimateScraper."""

from __future__ import annotations

import time as time_module
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

import resilience
import ultimate_scraper
from resilience import CircuitBreaker, CircuitState, DomainTierMemory, ResilienceRegistry


def _valid_html(text: str) -> str:
    body = f"<p>{text}</p>" * 40
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><title>T</title>"
        "<meta charset=\"utf-8\"></head>"
        f"<body>{body}</body></html>"
    )


@pytest.fixture
def fresh_registry(monkeypatch):
    """Provide a clean ResilienceRegistry and patch it into UltimateScraper."""
    reg = ResilienceRegistry()
    monkeypatch.setattr(resilience, "registry", reg)
    monkeypatch.setattr(ultimate_scraper, "registry", reg)
    return reg


@pytest.fixture
def frozen_time(monkeypatch):
    """Freeze time.time() for deterministic circuit-breaker tests."""
    now = 1_700_000_000.0

    def fake_time():
        return now

    monkeypatch.setattr(time_module, "time", fake_time)
    monkeypatch.setattr(resilience.time, "time", fake_time)
    monkeypatch.setattr(ultimate_scraper.time, "time", fake_time)
    return lambda offset=0: setattr(fake_time, "__wrapped__", None) or None


class TestCircuitBreaker:
    def test_starts_closed_and_allows(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.is_allowed() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_seconds=30)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_allowed() is True
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_allowed() is False

    def test_half_open_after_recovery(self, frozen_time, monkeypatch):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_seconds=60)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # Advance time past recovery window.
        now = 1_700_000_000.0 + 61
        monkeypatch.setattr(time_module, "time", lambda: now)
        monkeypatch.setattr(resilience.time, "time", lambda: now)
        assert cb.is_allowed() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_after_half_open_successes(self, frozen_time, monkeypatch):
        cb = CircuitBreaker(
            name="test", failure_threshold=1, recovery_seconds=60, half_open_max_tries=2
        )
        cb.record_failure()
        now = 1_700_000_000.0 + 61
        monkeypatch.setattr(time_module, "time", lambda: now)
        monkeypatch.setattr(resilience.time, "time", lambda: now)
        assert cb.is_allowed() is True
        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.is_allowed() is True
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self, frozen_time, monkeypatch):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_seconds=60)
        cb.record_failure()
        now = 1_700_000_000.0 + 61
        monkeypatch.setattr(time_module, "time", lambda: now)
        monkeypatch.setattr(resilience.time, "time", lambda: now)
        cb.is_allowed()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestDomainTierMemory:
    def test_picks_best_tier(self):
        mem = DomainTierMemory()
        mem.record("example.com", "direct", success=True, latency=0.1)
        mem.record("example.com", "direct", success=True, latency=0.1)
        mem.record("example.com", "playwright", success=False, latency=0.1)
        best = mem.best_tier("example.com", ["direct", "playwright"])
        assert best == "direct"

    def test_ignores_recent_failures(self, frozen_time, monkeypatch):
        mem = DomainTierMemory()
        now = 1_700_000_000.0
        monkeypatch.setattr(time_module, "time", lambda: now)
        mem.record("example.com", "direct", success=True, latency=0.1)
        mem.record("example.com", "direct", success=False, latency=0.1)
        assert mem.best_tier("example.com", ["direct"]) is None

    def test_returns_none_for_unknown_domain(self):
        mem = DomainTierMemory()
        assert mem.best_tier("example.com", ["direct"]) is None


class TestResilienceRegistry:
    def test_stats_shape(self, fresh_registry):
        stats = fresh_registry.stats()
        assert "circuit_breakers" in stats
        assert "domain_memory" in stats
        assert set(stats["circuit_breakers"].keys()) == set(ResilienceRegistry.SERVICE_NAMES)

    def test_service_result_toggles_breaker(self, fresh_registry):
        fresh_registry.breaker("flaresolverr").failure_threshold = 1
        fresh_registry.record_service_result("flaresolverr", False)
        assert fresh_registry.is_service_allowed("flaresolverr") is False
        fresh_registry.record_service_result("flaresolverr", True)
        # In half-open after recovery, not immediate.
        assert fresh_registry.breaker("flaresolverr").state == CircuitState.OPEN


_TIER_NAMES = [
    "_tier_direct",
    "_tier_tls_fingerprint",
    "_tier_cloudscraper",
    "_tier_flaresolverr",
    "_tier_undetected",
    "_tier_camoufox",
    "_tier_playwright",
    "_tier_googlebot",
    "_tier_premium_proxy",
    "_tier_archive",
    "_tier_google_cache",
    "_tier_tor",
]


class TestUltimateScraperResilience:
    @pytest.mark.anyio
    async def test_skips_circuit_open_tier(self, fresh_registry):
        scraper = ultimate_scraper.UltimateScraper()
        fresh_registry.breaker("flaresolverr").failure_threshold = 1
        fresh_registry.record_service_result("flaresolverr", False)

        html = _valid_html("archive content")
        mocks = {
            name: AsyncMock(return_value=None)
            for name in _TIER_NAMES
        }
        mocks["_tier_archive"].return_value = html
        with ExitStack() as stack:
            for name in _TIER_NAMES:
                stack.enter_context(patch.object(scraper, name, new=mocks[name]))
            result = await scraper.scrape("https://example.com/page")
        assert result["status"] == "ok"
        assert result["method"] == "archive"
        mocks["_tier_direct"].assert_awaited_once()
        mocks["_tier_cloudscraper"].assert_awaited_once()
        mocks["_tier_flaresolverr"].assert_not_awaited()

    @pytest.mark.anyio
    async def test_prefers_domain_memory_best_tier(self, fresh_registry):
        scraper = ultimate_scraper.UltimateScraper()
        fresh_registry.record_domain_tier_result("example.com", "archive", success=True)
        html = _valid_html("archived")
        mocks = {name: AsyncMock(return_value=None) for name in _TIER_NAMES}
        mocks["_tier_archive"].return_value = html
        mocks["_tier_direct"].return_value = _valid_html("direct")
        with ExitStack() as stack:
            for name in _TIER_NAMES:
                stack.enter_context(patch.object(scraper, name, new=mocks[name]))
            result = await scraper.scrape("https://example.com/page")
        assert result["status"] == "ok"
        assert result["method"] == "archive"
        mocks["_tier_archive"].assert_awaited()
        mocks["_tier_direct"].assert_not_awaited()

    @pytest.mark.anyio
    async def test_records_tier_results_after_success(self, fresh_registry):
        scraper = ultimate_scraper.UltimateScraper()
        html = _valid_html("direct content")
        mocks = {name: AsyncMock(return_value=None) for name in _TIER_NAMES}
        mocks["_tier_direct"].return_value = html
        with ExitStack() as stack:
            for name in _TIER_NAMES:
                stack.enter_context(patch.object(scraper, name, new=mocks[name]))
            await scraper.scrape("https://example.com/page")
        assert fresh_registry.best_tier_for_domain(
            "example.com", ["direct", "archive"]
        ) == "direct"

    @pytest.mark.anyio
    async def test_records_tier_failure_no_success_memory(self, fresh_registry):
        scraper = ultimate_scraper.UltimateScraper()
        mocks = {name: AsyncMock(return_value=None) for name in _TIER_NAMES}
        with ExitStack() as stack:
            for name in _TIER_NAMES:
                stack.enter_context(patch.object(scraper, name, new=mocks[name]))
            result = await scraper.scrape("https://example.com/page")
        assert result["status"] == "error"
        assert fresh_registry.best_tier_for_domain(
            "example.com", ["direct", "archive"]
        ) is None
