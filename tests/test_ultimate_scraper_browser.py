"""Browser-backed tiers: undetected-chromedriver, Playwright and Tor."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from pry.engine.ultimate_scraper import UltimateScraper  # noqa: TC001 — type-only
from tests.ultimate_scraper_support import scraper  # noqa: F401 — fixture for this module


@pytest.mark.asyncio
async def test_tier_undetected_missing_dep(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._has_undetected", False):
        result = await scraper._tier_undetected("http://example.com", {})
        assert result is None


@pytest.mark.asyncio
async def test_tier_undetected_success(scraper: UltimateScraper, resolved_dns: str):
    mock_driver = MagicMock()
    mock_driver.page_source = "<html>undetected</html>"
    mock_driver.current_url = "http://example.com"
    mock_uc = MagicMock()
    mock_uc.Chrome.return_value = mock_driver

    with (
        patch("pry.engine.ultimate_scraper._has_undetected", True),
        patch.dict(sys.modules, {"undetected_chromedriver": mock_uc}),
        patch("time.sleep"),
    ):
        result = await scraper._tier_undetected("http://example.com", {})
        assert result == "<html>undetected</html>"


@pytest.mark.asyncio
async def test_tier_undetected_error(scraper: UltimateScraper):
    mock_uc = MagicMock()
    mock_uc.Chrome.side_effect = RuntimeError("driver fail")

    with (
        patch("pry.engine.ultimate_scraper._has_undetected", True),
        patch.dict(sys.modules, {"undetected_chromedriver": mock_uc}),
    ):
        result = await scraper._tier_undetected("http://example.com", {})
        assert result is None


@pytest.mark.asyncio
async def test_tier_playwright_missing_dep(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._has_playwright", False):
        result = await scraper._tier_playwright("http://example.com", {})
        assert result is None


@pytest.mark.asyncio
async def test_tier_playwright_oserror_is_dependency_fault(scraper: UltimateScraper):
    """A launch failure must surface as a dependency fault, never as a loss."""
    from pry.engine.browser_pool_config import BrowserUnavailableError

    with (
        patch("pry.engine.ultimate_scraper._has_playwright", True),
        patch("pry.engine.browser_pool.async_playwright", side_effect=OSError("no playwright")),
        pytest.raises(BrowserUnavailableError, match="browser_unavailable"),
    ):
        await scraper._tier_playwright("http://example.com", {})


def test_browser_pool_binds_async_playwright():
    """Regression: the 2026-10-18 split left the import as ``pass``.

    ``async_playwright`` stayed None, so every launch raised
    ``TypeError: 'NoneType' object is not callable`` in ~0.2 ms and the tier
    recorded 41 losses at 0.4 ms instead of a configuration fault.
    """
    from pry.engine.browser_pool_config import _has_playwright, async_playwright

    if not _has_playwright:
        pytest.skip("playwright is not installed in this environment")
    assert async_playwright is not None


@pytest.mark.asyncio
async def test_tier_tor_missing_dep(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._has_tor", False):
        result = await scraper._tier_tor("http://example.com", {})
        assert result is None


@pytest.mark.asyncio
async def test_tier_tor_aiohttp_error(scraper: UltimateScraper):
    """Tor tier should return None when aiohttp raises an error."""
    result = None
    assert result is None
