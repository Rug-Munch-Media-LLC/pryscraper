"""Fingerprint-masking tiers: TLS impersonation and Camoufox."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pry.engine.ultimate_scraper import UltimateScraper
from tests.ultimate_scraper_support import scraper  # noqa: F401 — fixture for this module


@pytest.mark.asyncio
async def test_tier_tls_no_scraper(scraper: UltimateScraper):
    scraper._tls_scraper = None
    result = await scraper._tier_tls_fingerprint("http://example.com", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_tls_unavailable(scraper: UltimateScraper):
    mock_tls = MagicMock()
    mock_tls.is_available.return_value = False
    scraper._tls_scraper = mock_tls
    result = await scraper._tier_tls_fingerprint("http://example.com", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_tls_success(scraper: UltimateScraper):
    mock_tls = MagicMock()
    mock_tls.is_available.return_value = True
    mock_tls.fetch = AsyncMock(
        return_value={"success": True, "status_code": 200, "text": "<html>tls</html>"}
    )
    scraper._tls_scraper = mock_tls
    result = await scraper._tier_tls_fingerprint("http://example.com", {})
    assert result == "<html>tls</html>"


@pytest.mark.asyncio
async def test_tier_tls_failed(scraper: UltimateScraper):
    mock_tls = MagicMock()
    mock_tls.is_available.return_value = True
    mock_tls.fetch = AsyncMock(return_value={"success": False, "status_code": 403})
    scraper._tls_scraper = mock_tls
    result = await scraper._tier_tls_fingerprint("http://example.com", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_camoufox_no_browser(scraper: UltimateScraper):
    scraper._camoufox = None
    result = await scraper._tier_camoufox("http://example.com", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_camoufox_unavailable(scraper: UltimateScraper):
    mock_cf = MagicMock()
    mock_cf.is_available.return_value = False
    scraper._camoufox = mock_cf
    result = await scraper._tier_camoufox("http://example.com", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_camoufox_success(scraper: UltimateScraper):
    mock_cf = MagicMock()
    mock_cf.is_available.return_value = True
    mock_cf.fetch = AsyncMock(return_value={"success": True, "content": "<html>camoufox</html>"})
    scraper._camoufox = mock_cf
    result = await scraper._tier_camoufox("http://example.com", {})
    assert result == "<html>camoufox</html>"


@pytest.mark.asyncio
async def test_tier_camoufox_failed(scraper: UltimateScraper):
    mock_cf = MagicMock()
    mock_cf.is_available.return_value = True
    mock_cf.fetch = AsyncMock(return_value={"success": False})
    scraper._camoufox = mock_cf
    result = await scraper._tier_camoufox("http://example.com", {})
    assert result is None
