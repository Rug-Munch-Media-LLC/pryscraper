"""HTTP tiers: direct, premium proxy, cloudscraper and googlebot."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from pry.engine.ultimate_scraper import UltimateScraper
from tests.ultimate_scraper_support import scraper  # noqa: F401 — fixture for this module


@respx.mock
@pytest.mark.asyncio
async def test_tier_direct_success(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(
        return_value=httpx.Response(200, text="<html>OK</html>")
    )
    result = await scraper._tier_direct("http://example.com", {})
    assert result == "<html>OK</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_direct_http_error(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(side_effect=httpx.ConnectError("conn failed"))
    result = await scraper._tier_direct("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_premium_proxy_success(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(
        return_value=httpx.Response(200, text="<html>proxied</html>")
    )
    result = await scraper._tier_premium_proxy("http://example.com", "http://proxy:8080", {})
    assert result == "<html>proxied</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_premium_proxy_error(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(side_effect=httpx.ConnectError("proxy down"))
    result = await scraper._tier_premium_proxy("http://example.com", "http://proxy:8080", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_cloudscraper_missing_dep(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._has_cloudscraper", False):
        result = await scraper._tier_cloudscraper("http://example.com", {})
        assert result is None


@pytest.mark.asyncio
async def test_tier_cloudscraper_success(scraper: UltimateScraper):
    mock_scraper = MagicMock()
    mock_scraper.get.return_value.status_code = 200
    mock_scraper.get.return_value.encoding = "utf-8"
    mock_scraper.get.return_value.iter_content.return_value = [b"<html>cloud</html>"]

    with (
        patch("pry.engine.ultimate_scraper._has_cloudscraper", True),
        patch("cloudscraper.create_scraper", return_value=mock_scraper),
    ):
        result = await scraper._tier_cloudscraper("http://example.com", {})
        assert result == "<html>cloud</html>"


@pytest.mark.asyncio
async def test_tier_cloudscraper_error(scraper: UltimateScraper):
    with (
        patch("pry.engine.ultimate_scraper._has_cloudscraper", True),
        patch("cloudscraper.create_scraper", side_effect=RuntimeError("no cloudscraper")),
    ):
        result = await scraper._tier_cloudscraper("http://example.com", {})
        assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_googlebot_success(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(
        return_value=httpx.Response(200, text="<html>googlebot</html>")
    )
    result = await scraper._tier_googlebot("http://example.com", {})
    assert result == "<html>googlebot</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_googlebot_error(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(side_effect=httpx.ConnectError("fail"))
    result = await scraper._tier_googlebot("http://example.com", {})
    assert result is None
