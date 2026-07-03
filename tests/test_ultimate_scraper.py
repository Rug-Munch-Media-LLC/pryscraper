"""Tests for ultimate scraper fallback chain."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import resilience
from ultimate_scraper import UltimateScraper


def _clear_registry() -> None:
    """Reset global resilience registry to avoid cross-test contamination."""
    resilience.registry.domain_memory.data.clear()
    for name in list(resilience.registry.breakers.keys()):
        cb = resilience.registry.breakers[name]
        cb.state = "closed"
        cb.failures = 0
        cb.successes = 0
        cb.last_failure_at = 0.0
        cb.half_open_attempts = 0


_TIER_ALL = [
    "_tier_direct", "_tier_tls_fingerprint", "_tier_cloudscraper",
    "_tier_flaresolverr", "_tier_undetected", "_tier_camoufox",
    "_tier_playwright", "_tier_googlebot", "_tier_premium_proxy",
    "_tier_archive", "_tier_google_cache", "_tier_tor",
]

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
    _clear_registry()
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
    _clear_registry()
    s = UltimateScraper()
    html = "<html><body>" + "x" * 1000 + "</body></html>"
    ctx_mocks = {name: AsyncMock(return_value=None) for name in _TIER_ALL}
    ctx_mocks["_tier_tls_fingerprint"].return_value = html
    with ExitStack() as stack:
        for name in _TIER_ALL:
            stack.enter_context(patch.object(s, name, new=ctx_mocks[name]))
        result = await s.scrape("http://example.com")
        assert result["status"] == "ok"
        assert result["method"] == "tls_fingerprint"


@pytest.mark.anyio
async def test_scrape_camoufox_tier_succeeds() -> None:
    _clear_registry()
    s = UltimateScraper()
    html = "<html><body>" + "x" * 1000 + "</body></html>"
    ctx_mocks = {name: AsyncMock(return_value=None) for name in _TIER_ALL}
    ctx_mocks["_tier_camoufox"].return_value = html
    with ExitStack() as stack:
        for name in _TIER_ALL:
            stack.enter_context(patch.object(s, name, new=ctx_mocks[name]))
        result = await s.scrape("http://example.com")
        assert result["status"] == "ok"
        assert result["method"] == "camoufox"
