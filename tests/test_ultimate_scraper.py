# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for ultimate_scraper.py — multi-strategy anti-detection scraper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ultimate_scraper import UltimateScraper

_VALID_HTML = "<html><body>" + "x" * 600 + "</body></html>"
_VALID_HTML_2 = "<html><body>" + "y" * 600 + "</body></html>"
_VALID_HTML_3 = "<html><body>" + "z" * 600 + "</body></html>"


@pytest.fixture
def scraper() -> UltimateScraper:
    """Return a scraper with a clean registry mock so test pollution is impossible."""
    with (
        patch("ultimate_scraper.registry.reorder_for_domain", side_effect=lambda _d, c: c),
        patch("ultimate_scraper.registry.is_service_allowed", return_value=True),
        patch("ultimate_scraper.registry.record_domain_tier_result"),
        patch("ultimate_scraper.registry.record_service_result"),
    ):
        yield UltimateScraper()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def test_scraper_init(scraper: UltimateScraper):
    assert scraper is not None
    for t in ["_tier_direct", "_tier_tor", "_tier_archive", "_tier_google_cache"]:
        assert hasattr(scraper, t)


def test_scraper_has_all_tiers(scraper: UltimateScraper):
    tiers = [
        "_tier_direct",
        "_tier_premium_proxy",
        "_tier_cloudscraper",
        "_tier_flaresolverr",
        "_tier_undetected",
        "_tier_playwright",
        "_tier_tls_fingerprint",
        "_tier_camoufox",
        "_tier_googlebot",
        "_tier_archive",
        "_tier_google_cache",
        "_tier_tor",
    ]
    for t in tiers:
        assert hasattr(scraper, t), f"Missing tier: {t}"


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_invalid_url_returns_error(scraper: UltimateScraper):
    result = await scraper.scrape("not-a-url")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# UA rotation
# ---------------------------------------------------------------------------


def test_rotate_ua_returns_string(scraper: UltimateScraper):
    ua = scraper._rotate_ua()
    assert isinstance(ua, str) and len(ua) > 20


def test_rotate_ua_changes(scraper: UltimateScraper):
    uas = {scraper._rotate_ua() for _ in range(5)}
    assert len(uas) > 1


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


def test_build_headers_contains_required(scraper: UltimateScraper):
    h = scraper._build_headers("http://example.com")
    for k in ["User-Agent", "Accept", "Accept-Language"]:
        assert k in h


# ---------------------------------------------------------------------------
# _is_valid
# ---------------------------------------------------------------------------


def test_is_valid_none(scraper: UltimateScraper):
    assert scraper._is_valid(None) is False


def test_is_valid_empty(scraper: UltimateScraper):
    assert scraper._is_valid("") is False


def test_is_valid_short(scraper: UltimateScraper):
    assert scraper._is_valid("ab" * 100) is False


def test_is_valid_ok(scraper: UltimateScraper):
    assert scraper._is_valid(_VALID_HTML) is True


def test_is_valid_body_text_too_short(scraper: UltimateScraper):
    body = "<body>" + "x" * 40 + "</body>"
    assert scraper._is_valid(body) is False


# ---------------------------------------------------------------------------
# _result
# ---------------------------------------------------------------------------


def test_result_success_format(scraper: UltimateScraper):
    result = scraper._result("http://example.com", _VALID_HTML, "direct")
    assert result["status"] == "ok"
    assert result["url"] == "http://example.com"
    assert result["method"] == "direct"
    assert "raw_html" in result


def test_result_contains_block_signal(scraper: UltimateScraper):
    result = scraper._result(
        "http://example.com",
        _VALID_HTML,
        "direct",
        block_signal={"kind": "captcha", "confidence": 0.8},
    )
    assert result["block_signal"]["kind"] == "captcha"


# ---------------------------------------------------------------------------
# Proxy resolution
# ---------------------------------------------------------------------------


def test_resolve_proxy_url_from_opts(scraper: UltimateScraper):
    url = scraper._resolve_proxy_url({"proxy_url": "http://proxy:8080"})
    assert url == "http://proxy:8080"


def test_resolve_proxy_url_none(scraper: UltimateScraper):
    assert scraper._resolve_proxy_url({}) is None


# ---------------------------------------------------------------------------
# scrape — fallback chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_direct_success(scraper: UltimateScraper):
    with patch.object(scraper, "_tier_direct", new=AsyncMock(return_value=_VALID_HTML)):
        result = await scraper.scrape("http://example.com")
        assert result["status"] == "ok" and result["method"] == "direct"


@pytest.mark.asyncio
async def test_scrape_all_tiers_fail(scraper: UltimateScraper):
    for t in [
        "_tier_direct",
        "_tier_tls_fingerprint",
        "_tier_cloudscraper",
        "_tier_flaresolverr",
        "_tier_undetected",
        "_tier_camoufox",
        "_tier_playwright",
        "_tier_googlebot",
        "_tier_tor",
        "_tier_archive",
        "_tier_google_cache",
    ]:
        if hasattr(scraper, t):
            setattr(scraper, t, AsyncMock(return_value=None))
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_scrape_second_tier_works(scraper: UltimateScraper):
    scraper._tier_direct = AsyncMock(return_value=None)
    scraper._tier_tls_fingerprint = AsyncMock(return_value=_VALID_HTML_2)
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "ok" and "tls" in result.get("method", "")


@pytest.mark.asyncio
async def test_scrape_archive_fallback(scraper: UltimateScraper):
    for t in [
        "_tier_direct",
        "_tier_tls_fingerprint",
        "_tier_cloudscraper",
        "_tier_flaresolverr",
        "_tier_undetected",
        "_tier_camoufox",
        "_tier_playwright",
        "_tier_googlebot",
        "_tier_tor",
    ]:
        if hasattr(scraper, t):
            setattr(scraper, t, AsyncMock(return_value=None))
    scraper._tier_archive = AsyncMock(return_value=_VALID_HTML_3)
    scraper._tier_google_cache = AsyncMock(return_value=None)
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "ok" and result["method"] == "archive"


# ---------------------------------------------------------------------------
# Tier exception handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_tier_exception_handled(scraper: UltimateScraper):
    scraper._tier_direct = AsyncMock(side_effect=RuntimeError("boom"))
    scraper._tier_tls_fingerprint = AsyncMock(return_value=_VALID_HTML)
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def test_record_telemetry_noop(scraper: UltimateScraper):
    with patch("ultimate_scraper._HAS_FALLBACK_TELEMETRY", False):
        scraper._record_telemetry("example.com", ["direct"], [], "direct", True, 0.0, [])


# ---------------------------------------------------------------------------
# _signal_to_dict
# ---------------------------------------------------------------------------


def test_signal_to_dict(scraper: UltimateScraper):
    signal = MagicMock(
        kind="captcha", confidence=0.95, recommended_escalation="playwright", evidence=set()
    )
    d = scraper._signal_to_dict(signal)
    assert d["kind"] == "captcha" and d["confidence"] == 0.95


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_with_retry(scraper: UltimateScraper):
    scraper._tier_direct = AsyncMock(return_value=_VALID_HTML)
    result = await scraper.scrape("http://example.com", options={"retry": {"max_attempts": 2}})
    assert result["status"] == "ok"
