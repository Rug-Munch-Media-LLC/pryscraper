"""UltimateScraper fallback chain, proxy resolution, telemetry and retry."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pry.engine.ultimate_scraper import UltimateScraper
from tests.ultimate_scraper_support import (  # noqa: F401 — fixtures for this module
    VALID_HTML,
    VALID_HTML_2,
    VALID_HTML_3,
    scraper,
)

_ORDERED_TIERS = [
    "_tier_direct",
    "_tier_tls_fingerprint",
    "_tier_cloudscraper",
    "_tier_flaresolverr",
    "_tier_undetected",
    "_tier_camoufox",
    "_tier_playwright",
    "_tier_googlebot",
    "_tier_tor",
]


def test_resolve_proxy_url_from_opts(scraper: UltimateScraper):
    url = scraper._resolve_proxy_url({"proxy_url": "http://proxy:8080"})
    assert url == "http://proxy:8080"


def test_resolve_proxy_url_none(scraper: UltimateScraper):
    assert scraper._resolve_proxy_url({}) is None


@pytest.mark.asyncio
async def test_scrape_direct_success(scraper: UltimateScraper):
    with patch.object(scraper, "_tier_direct", new=AsyncMock(return_value=VALID_HTML)):
        result = await scraper.scrape("http://example.com")
        assert result["status"] == "ok"
        assert result["method"] == "direct"


@pytest.mark.asyncio
async def test_scrape_all_tiers_fail(scraper: UltimateScraper):
    for t in [*_ORDERED_TIERS, "_tier_archive", "_tier_google_cache"]:
        if hasattr(scraper, t):
            setattr(scraper, t, AsyncMock(return_value=None))
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_scrape_second_tier_works(scraper: UltimateScraper):
    scraper._tier_direct = AsyncMock(return_value=None)
    scraper._tier_tls_fingerprint = AsyncMock(return_value=VALID_HTML_2)
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "ok"
    assert "tls" in result.get("method", "")


@pytest.mark.asyncio
async def test_scrape_archive_fallback(scraper: UltimateScraper):
    for t in _ORDERED_TIERS:
        if hasattr(scraper, t):
            setattr(scraper, t, AsyncMock(return_value=None))
    scraper._tier_archive = AsyncMock(return_value=VALID_HTML_3)
    scraper._tier_google_cache = AsyncMock(return_value=None)
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "ok"
    assert result["method"] == "archive"


@pytest.mark.asyncio
async def test_scrape_tier_exception_handled(scraper: UltimateScraper):
    scraper._tier_direct = AsyncMock(side_effect=RuntimeError("boom"))
    scraper._tier_tls_fingerprint = AsyncMock(return_value=VALID_HTML)
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "ok"


def test_record_telemetry_noop(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._HAS_FALLBACK_TELEMETRY", False):
        scraper._record_telemetry("example.com", ["direct"], [], "direct", True, 0.0, [])


def test_signal_to_dict(scraper: UltimateScraper):
    signal = MagicMock(
        kind="captcha", confidence=0.95, recommended_escalation="playwright", evidence=set()
    )
    d = scraper._signal_to_dict(signal)
    assert d["kind"] == "captcha"
    assert d["confidence"] == 0.95


@pytest.mark.asyncio
async def test_scrape_with_retry(scraper: UltimateScraper):
    scraper._tier_direct = AsyncMock(return_value=VALID_HTML)
    result = await scraper.scrape("http://example.com", options={"retry": {"max_attempts": 2}})
    assert result["status"] == "ok"
