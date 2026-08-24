"""Tests for resilience primitives and their integration into UltimateScraper."""

from __future__ import annotations

import time as time_module
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from pry.engine import resilience, ultimate_scraper
from pry.engine.resilience import CircuitBreaker, CircuitState, DomainTierMemory, ResilienceRegistry


def _valid_html(text: str) -> str:
    body = f"<p>{text}</p>" * 40
    return (
        '<!DOCTYPE html><html lang="en"><head><title>T</title>'
        '<meta charset="utf-8"></head>'
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


_CANDIDATES = [
    "direct",
    "tls_fingerprint",
    "cloudscraper",
    "flaresolverr",
    "undetected",
    "camoufox",
    "playwright",
    "googlebot",
    "tor",
    "premium_proxy",
    "archive",
    "google_cache",
]


class TestReorderForDomain:
    def test_promotes_proven_tier_to_front(self):
        mem = DomainTierMemory()
        for _ in range(3):
            mem.record("example.com", "archive", success=True, latency=0.1)
        ordered = mem.reorder_for_domain("example.com", _CANDIDATES)
        assert ordered[0] == "archive"
        # Every candidate is still present.
        assert set(ordered) == set(_CANDIDATES)

    def test_skips_chronic_failure_tier(self):
        mem = DomainTierMemory()
        for _ in range(3):
            mem.record("example.com", "direct", success=False, latency=0.1)
        ordered = mem.reorder_for_domain("example.com", _CANDIDATES)
        assert "direct" not in ordered

    def test_keeps_tier_with_few_failures_below_sample_threshold(self):
        mem = DomainTierMemory()
        # 2 failures < DOMAIN_FAILURE_SKIP_MIN_SAMPLES -> not skipped.
        for _ in range(2):
            mem.record("example.com", "direct", success=False, latency=0.1)
        ordered = mem.reorder_for_domain("example.com", _CANDIDATES)
        assert "direct" in ordered

    def test_demotes_recent_failure_on_cooldown(self, frozen_time):
        mem = DomainTierMemory()
        mem.record("example.com", "direct", success=True, latency=0.1)
        # Failure at the frozen "now" puts direct on cooldown.
        mem.record("example.com", "direct", success=False, latency=0.1)
        ordered = mem.reorder_for_domain("example.com", _CANDIDATES)
        assert "direct" in ordered
        assert ordered[-1] == "direct"

    def test_returns_static_order_for_unknown_domain(self):
        mem = DomainTierMemory()
        assert mem.reorder_for_domain("example.com", _CANDIDATES) == _CANDIDATES

    def test_never_empty_when_all_candidates_skipped(self):
        mem = DomainTierMemory()
        for tier in ["direct", "tls_fingerprint", "archive"]:
            for _ in range(3):
                mem.record("example.com", tier, success=False, latency=0.1)
        candidates = ["direct", "tls_fingerprint", "archive"]
        ordered = mem.reorder_for_domain("example.com", candidates)
        # Falls back to the static order so the scraper always tries something.
        assert ordered == candidates

    def test_registry_wrapper_delegates(self):
        reg = ResilienceRegistry()
        for _ in range(3):
            reg.record_domain_tier_result("example.com", "archive", success=True, latency=0.1)
        ordered = reg.reorder_for_domain("example.com", _CANDIDATES)
        assert ordered[0] == "archive"


class TestResiliencePersistence:
    def test_disabled_by_default(self, tmp_path):
        reg = ResilienceRegistry()
        reg.record_domain_tier_result("example.com", "direct", success=True, latency=0.1)
        assert reg.save() is False
        assert not (tmp_path / "resilience_state.json").exists()

    def test_roundtrip_domain_memory_and_breakers(self, tmp_path):
        path = tmp_path / "resilience_state.json"
        reg = ResilienceRegistry(persist_path=path)
        reg.record_domain_tier_result("example.com", "direct", True, latency=0.1)
        reg.record_domain_tier_result("example.com", "direct", True, latency=0.1)
        reg.record_domain_tier_result("example.com", "archive", False, latency=0.1)
        reg.breaker("flaresolverr").failure_threshold = 1
        reg.record_service_result("flaresolverr", False)
        assert reg.save() is True
        assert path.exists()

        reloaded = ResilienceRegistry(persist_path=path)
        assert reloaded.best_tier_for_domain("example.com", ["direct", "archive"]) == "direct"
        assert reloaded.breaker("flaresolverr").state == CircuitState.OPEN

    def test_roundtrip_survives_adaptive_reorder(self, tmp_path):
        path = tmp_path / "resilience_state.json"
        reg = ResilienceRegistry(persist_path=path)
        for _ in range(3):
            reg.record_domain_tier_result("example.com", "archive", True, latency=0.1)
        reg.save()

        reloaded = ResilienceRegistry(persist_path=path)
        ordered = reloaded.reorder_for_domain("example.com", _CANDIDATES)
        assert ordered[0] == "archive"

    def test_load_non_fatal_on_corrupt_file(self, tmp_path):
        path = tmp_path / "resilience_state.json"
        path.write_text("{not valid json", encoding="utf-8")
        reg = ResilienceRegistry(persist_path=path)  # must not raise
        assert reg.best_tier_for_domain("example.com", ["direct"]) is None

    def test_save_non_fatal_on_io_error(self, tmp_path):
        # Point persistence at a directory — open() raises OSError.
        reg = ResilienceRegistry(persist_path=tmp_path)
        reg.record_domain_tier_result("example.com", "direct", True, latency=0.1)
        assert reg.save() is False  # must not raise


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
        mocks = {name: AsyncMock(return_value=None) for name in _TIER_NAMES}
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
        assert fresh_registry.best_tier_for_domain("example.com", ["direct", "archive"]) == "direct"

    @pytest.mark.anyio
    async def test_records_tier_failure_no_success_memory(self, fresh_registry):
        scraper = ultimate_scraper.UltimateScraper()
        mocks = {name: AsyncMock(return_value=None) for name in _TIER_NAMES}
        with ExitStack() as stack:
            for name in _TIER_NAMES:
                stack.enter_context(patch.object(scraper, name, new=mocks[name]))
            result = await scraper.scrape("https://example.com/page")
        assert result["status"] == "error"
        assert fresh_registry.best_tier_for_domain("example.com", ["direct", "archive"]) is None
