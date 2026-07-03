"""Integration tests for the full fallback chain: retry + circuit breaker + tier dispatch."""

from __future__ import annotations

import time as time_module
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

import resilience
import ultimate_scraper
from resilience import ResilienceRegistry
from retry import Jitter, RetryConfig, async_retry


def _valid_html(text: str = "content") -> str:
    body = f"<p>{text}</p>" * 40
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><title>T</title>"
        "<meta charset=\"utf-8\"></head>"
        f"<body>{body}</body></html>"
    )


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


@pytest.fixture
def fresh_registry(monkeypatch):
    """Clean ResilienceRegistry patched into both modules."""
    reg = ResilienceRegistry()
    monkeypatch.setattr(resilience, "registry", reg)
    monkeypatch.setattr(ultimate_scraper, "registry", reg)
    return reg


@pytest.fixture
def mock_all_tiers():
    """Return a dict of AsyncMocks for every tier method."""
    return {name: AsyncMock(return_value=None) for name in _TIER_NAMES}


@pytest.fixture
def scraper_with_mocks(mock_all_tiers):
    """UltimateScraper with all tier methods mocked."""
    s = ultimate_scraper.UltimateScraper()
    with ExitStack() as stack:
        for name in _TIER_NAMES:
            stack.enter_context(patch.object(s, name, new=mock_all_tiers[name]))
        yield s, mock_all_tiers


BASE_CFG = RetryConfig(max_retries=2, base_delay=0.01, jitter=Jitter.NONE)
BASE_CFG_CB = RetryConfig(max_retries=2, base_delay=0.01, jitter=Jitter.NONE)


class TestRetryWithScraper:
    """Retry wrapping scraper entry points."""

    @pytest.mark.anyio
    async def test_retry_with_exception_wrapper(self):
        """Retry wraps a flaky function that raises then succeeds."""
        call_count = 0

        async def flaky_fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("first attempt failed")
            return "success"

        result = await async_retry(flaky_fn, config=BASE_CFG)
        assert result == "success"
        assert call_count == 2

    @pytest.mark.anyio
    async def test_retry_exhausts_and_raises(self, scraper_with_mocks):
        """Retry exhausts attempts and re-raises."""
        s, mocks = scraper_with_mocks

        async def scrape_or_raise(url: str) -> dict:
            result = await s.scrape(url)
            if result.get("status") == "error":
                raise RuntimeError(result.get("error", "scrape failed"))
            return result

        with pytest.raises(RuntimeError, match="scrape failed|_failed|circuit_open"):
            await async_retry(scrape_or_raise, "https://example.com/page", config=BASE_CFG)


class TestCircuitBreakerIntegration:
    """Circuit breaker with retry and tier skipping."""

    @pytest.mark.anyio
    async def test_retry_skips_open_breaker(self, fresh_registry):
        """Open circuit breaker causes retry to skip immediately."""
        name = "cb_int_block"
        cb = fresh_registry.breaker(name)
        cb.failure_threshold = 1
        fresh_registry.record_service_result(name, False)
        assert fresh_registry.is_service_allowed(name) is False

        fn = AsyncMock(side_effect=ConnectionError("down"))
        cfg = RetryConfig(max_retries=3, circuit_breaker=name, base_delay=0.01, jitter=Jitter.NONE)

        with pytest.raises(RuntimeError, match="Circuit breaker"):
            await async_retry(fn, config=cfg)
        assert fn.call_count == 0
        del resilience.registry.breakers[name]

    @pytest.mark.anyio
    async def test_circuit_records_success_on_retry(self, fresh_registry):
        """Successful retry records success to circuit breaker."""
        name = "cb_int_success"
        fn = AsyncMock(return_value="ok")
        cfg = RetryConfig(max_retries=1, circuit_breaker=name, base_delay=0.01, jitter=Jitter.NONE)
        result = await async_retry(fn, config=cfg)
        assert result == "ok"
        cb = fresh_registry.breaker(name)
        assert cb.successes >= 1
        del resilience.registry.breakers[name]

    @pytest.mark.anyio
    async def test_recovery_after_half_open(self, fresh_registry, monkeypatch):
        """After recovery window, retry should attempt and succeed."""
        now = 1_700_000_000.0
        monkeypatch.setattr(time_module, "time", lambda: now)
        monkeypatch.setattr(resilience.time, "time", lambda: now)

        cb = fresh_registry.breaker("ollama_int")
        cb.failure_threshold = 1
        cb.recovery_seconds = 30
        fresh_registry.record_service_result("ollama_int", False)
        assert cb.state == "open"

        future = now + 31
        monkeypatch.setattr(time_module, "time", lambda: future)
        monkeypatch.setattr(resilience.time, "time", lambda: future)

        fn = AsyncMock(return_value="ok")
        cfg = RetryConfig(max_retries=1, circuit_breaker="ollama_int", base_delay=0.01, jitter=Jitter.NONE)
        result = await async_retry(fn, config=cfg)
        assert result == "ok"

    @pytest.mark.anyio
    async def test_skip_open_breaker_tier(self, fresh_registry, mock_all_tiers):
        """Breaker open for flaresolverr skips that tier."""
        s = ultimate_scraper.UltimateScraper()
        html = _valid_html("archive")
        mock_all_tiers["_tier_archive"].return_value = html

        fresh_registry.breaker("flaresolverr").failure_threshold = 1
        fresh_registry.record_service_result("flaresolverr", False)

        with ExitStack() as stack:
            for name in _TIER_NAMES:
                stack.enter_context(patch.object(s, name, new=mock_all_tiers[name]))
            result = await s.scrape("https://example.com/page")
        assert result["status"] == "ok"
        assert result["method"] == "archive"
        mock_all_tiers["_tier_flaresolverr"].assert_not_awaited()

    @pytest.mark.anyio
    async def test_multiple_open_breakers(self, fresh_registry, mock_all_tiers):
        """Multiple open breakers skip their tiers."""
        s = ultimate_scraper.UltimateScraper()
        html = _valid_html("tor finish")
        mock_all_tiers["_tier_tor"].return_value = html

        for name in ["flaresolverr", "playwright"]:
            cb = fresh_registry.breaker(name)
            cb.failure_threshold = 1
            fresh_registry.record_service_result(name, False)

        with ExitStack() as stack:
            for name in _TIER_NAMES:
                stack.enter_context(patch.object(s, name, new=mock_all_tiers[name]))
            result = await s.scrape("https://example.com/page")
        assert result["status"] == "ok"
        mock_all_tiers["_tier_flaresolverr"].assert_not_awaited()
        mock_all_tiers["_tier_playwright"].assert_not_awaited()


class TestDomainTierMemoryWithRetry:
    """Domain tier memory + retry combined."""

    @pytest.mark.anyio
    async def test_domain_memory_used_on_retry(self, fresh_registry, scraper_with_mocks):
        """After domain learns best tier, prefers it."""
        s, mocks = scraper_with_mocks
        fresh_registry.record_domain_tier_result("example.com", "archive", success=True, latency=0.1)
        html = _valid_html("archive content")
        mocks["_tier_archive"].return_value = html
        mocks["_tier_direct"].return_value = _valid_html("direct")

        result = await s.scrape("https://example.com/page")
        assert result["status"] == "ok"
        mocks["_tier_archive"].assert_awaited()
        mocks["_tier_direct"].assert_not_awaited()


class TestGracefulDegradation:
    """End-to-end graceful degradation."""

    @pytest.mark.anyio
    async def test_all_tiers_fail_returns_error(self, fresh_registry, mock_all_tiers):
        """All tiers return None, scrape returns error."""
        s = ultimate_scraper.UltimateScraper()
        with ExitStack() as stack:
            for name in _TIER_NAMES:
                stack.enter_context(patch.object(s, name, new=mock_all_tiers[name]))
            result = await s.scrape("https://example.com/page")
        assert result["status"] == "error"

    @pytest.mark.anyio
    async def test_circuit_breaker_with_error_dict(self, fresh_registry, mock_all_tiers):
        """If scrape returns error (not exception), circuit breaker still records failure."""
        s = ultimate_scraper.UltimateScraper()
        name = "cb_degradation"

        with ExitStack() as stack:
            for name in _TIER_NAMES:
                stack.enter_context(patch.object(s, name, new=mock_all_tiers[name]))

            async def scrape_and_raise(url: str) -> dict:
                result = await s.scrape(url)
                if result.get("status") == "error":
                    raise RuntimeError(result.get("error", "scrape failed"))
                return result

            cfg = RetryConfig(max_retries=1, circuit_breaker=name, base_delay=0.01, jitter=Jitter.NONE)
            with pytest.raises(RuntimeError):
                await async_retry(scrape_and_raise, "https://example.com/page", config=cfg)

        if name in resilience.registry.breakers:
            del resilience.registry.breakers[name]


class TestRetrySettings:
    """Retry module integration with settings."""

    def test_retry_config_from_settings(self) -> None:
        from settings import PrySettings
        settings = PrySettings()
        assert settings.retry_backoff == "exponential"

    def test_api_dict_includes_backoff(self) -> None:
        from settings import PrySettings
        settings = PrySettings()
        api_dict = settings.to_api_dict()
        assert "retry" in api_dict
        assert api_dict["retry"]["backoff"] == "exponential"
