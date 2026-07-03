# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for ultimate scraper fallback chain."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ultimate_scraper import UltimateScraper


def test_ultimate_init() -> None:
    s = UltimateScraper()
    assert s is not None
    assert len(s.USER_AGENTS) >= 3


def test_rotate_ua_changes() -> None:
    s = UltimateScraper()
    ua1 = s._rotate_ua()
    ua2 = s._rotate_ua()
    assert isinstance(ua1, str)
    assert isinstance(ua2, str)


def test_is_valid_empty() -> None:
    s = UltimateScraper()
    assert s._is_valid("") is False
    assert s._is_valid("<html></html>") is False
    assert s._is_valid(None) is False


@pytest.mark.anyio
async def test_tier_tls_fingerprint_not_available() -> None:
    s = UltimateScraper()
    s._tls_scraper = None
    result = await s._tier_tls_fingerprint("http://example.com", {}, None)
    assert result is None


@pytest.mark.anyio
async def test_tier_tls_fingerprint_success() -> None:
    s = UltimateScraper()
    mock = MagicMock()
    mock.is_available.return_value = True
    mock.fetch = AsyncMock(
        return_value={
            "success": True,
            "status_code": 200,
            "text": "<html><body>hello world</body></html>",
        }
    )
    s._tls_scraper = mock
    result = await s._tier_tls_fingerprint("http://example.com", {}, None)
    assert result == "<html><body>hello world</body></html>"


@pytest.mark.anyio
async def test_tier_tls_fingerprint_failure() -> None:
    s = UltimateScraper()
    mock = MagicMock()
    mock.is_available.return_value = True
    mock.fetch = AsyncMock(return_value={"success": False, "error": "blocked"})
    s._tls_scraper = mock
    result = await s._tier_tls_fingerprint("http://example.com", {}, None)
    assert result is None


@pytest.mark.anyio
async def test_tier_camoufox_not_available() -> None:
    s = UltimateScraper()
    s._camoufox = None
    result = await s._tier_camoufox("http://example.com", {}, None)
    assert result is None


@pytest.mark.anyio
async def test_tier_camoufox_success() -> None:
    s = UltimateScraper()
    mock = MagicMock()
    mock.is_available.return_value = True
    mock.fetch = AsyncMock(
        return_value={
            "success": True,
            "content": "<html><body>camoufox result</body></html>",
        }
    )
    s._camoufox = mock
    result = await s._tier_camoufox("http://example.com", {}, None)
    assert result == "<html><body>camoufox result</body></html>"


@pytest.mark.anyio
async def test_tier_camoufox_failure() -> None:
    s = UltimateScraper()
    mock = MagicMock()
    mock.is_available.return_value = True
    mock.fetch = AsyncMock(return_value={"success": False, "error": "blocked"})
    s._camoufox = mock
    result = await s._tier_camoufox("http://example.com", {}, None)
    assert result is None


@pytest.mark.anyio
async def test_scrape_falls_through_all_tiers() -> None:
    s = UltimateScraper()
    with patch.object(s, "_tier_direct", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_tls_fingerprint", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_cloudscraper", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_flaresolverr", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_undetected", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_camoufox", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_playwright", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_googlebot", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_archive", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_google_cache", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_tor", new=AsyncMock(return_value=None)):
        result = await s.scrape("http://example.com")
        assert result["status"] == "error"


@pytest.mark.anyio
async def test_scrape_tls_tier_succeeds() -> None:
    s = UltimateScraper()
    html = "<html><body>" + "x" * 1000 + "</body></html>"
    with patch.object(s, "_tier_direct", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_tls_fingerprint", new=AsyncMock(return_value=html)), \
         patch.object(s, "_tier_cloudscraper", new=AsyncMock(return_value=None)):
        result = await s.scrape("http://example.com")
        assert result["status"] == "ok"
        assert result["method"] == "tls_fingerprint"


@pytest.mark.anyio
async def test_scrape_camoufox_tier_succeeds() -> None:
    s = UltimateScraper()
    html = "<html><body>" + "x" * 1000 + "</body></html>"
    with patch.object(s, "_tier_direct", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_tls_fingerprint", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_cloudscraper", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_flaresolverr", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_undetected", new=AsyncMock(return_value=None)), \
         patch.object(s, "_tier_camoufox", new=AsyncMock(return_value=html)):
        result = await s.scrape("http://example.com")
        assert result["status"] == "ok"
        assert result["method"] == "camoufox"
