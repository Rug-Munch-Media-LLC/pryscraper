"""Archive tiers: Wayback Machine and Google cache (incl. interstitial rejection)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import httpx
import pytest
import respx

from pry.engine.ultimate_scraper import UltimateScraper
from tests.ultimate_scraper_support import scraper  # noqa: F401 — fixture for this module

CDX = "https://web.archive.org/cdx/"


@respx.mock
@pytest.mark.asyncio
async def test_tier_archive_success(scraper: UltimateScraper, resolved_dns: str):
    # CDX API response
    respx.get(url__startswith=CDX).mock(
        return_value=httpx.Response(
            200, json=[["timestamp", "original"], ["20250101000000", "http://example.com"]]
        )
    )
    # Archive snapshot
    respx.get(url__startswith=f"https://{resolved_dns}/web/").mock(
        return_value=httpx.Response(200, text="<html>archived</html>")
    )
    result = await scraper._tier_archive("http://example.com", {})
    assert result == "<html>archived</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_archive_no_results(scraper: UltimateScraper):
    respx.get(url__startswith=CDX).mock(
        return_value=httpx.Response(200, json=[["timestamp", "original"]])
    )
    result = await scraper._tier_archive("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_archive_http_error(scraper: UltimateScraper):
    respx.get(url__startswith=CDX).mock(side_effect=httpx.ConnectError("archive down"))
    result = await scraper._tier_archive("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_success(scraper: UltimateScraper, resolved_dns: str):
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(200, text="<html>cached</html>")
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result == "<html>cached</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_error(scraper: UltimateScraper, resolved_dns: str):
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        side_effect=httpx.ConnectError("cache down")
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_rejects_search_interstitial(
    scraper: UltimateScraper, resolved_dns: str
):
    """A Google search page served with HTTP 200 must not be a fake success."""
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body><form action='/search'>"
                "<input name='q'><a href='https://www.google.com/search?q=example'>"
                "Search</a></body></html>"
            ),
        )
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_rejects_consent_page(scraper: UltimateScraper, resolved_dns: str):
    """A Google consent interstitial must be rejected, not returned as content."""
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body><h1>Before you continue to Google</h1>"
                "<a href='https://consent.google.com/m?continue=x'>I agree</a>"
                "</body></html>"
            ),
        )
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_rejects_unusual_traffic_captcha(
    scraper: UltimateScraper, resolved_dns: str
):
    """Google's 'unusual traffic' CAPTCHA page must be rejected."""
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body>Our systems have detected unusual traffic from your "
                "computer network. <div id='captcha-form'></div></body></html>"
            ),
        )
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_rejects_redirect_notice(
    scraper: UltimateScraper, resolved_dns: str
):
    """Google's post-webcache 'redirect notice' page must be rejected.

    Google discontinued webcache in 2024; the endpoint now serves this notice
    with HTTP 200 for every query.
    """
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body>Please click here if you are not redirected within "
                "a few seconds. If you're having trouble accessing Google Search, "
                "please click here, or send feedback.</body></html>"
            ),
        )
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_accepts_real_cached_content(
    scraper: UltimateScraper, resolved_dns: str
):
    """A genuine cached document (no Google markers) is still returned."""
    cached = "<html><body>" + "real cached article body " * 40 + "</body></html>"
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(200, text=cached)
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result == cached
