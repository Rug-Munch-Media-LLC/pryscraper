"""FlareSolverr tier: configuration, success and failure diagnostics."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx

from pry.engine.ultimate_scraper import UltimateScraper
from tests.ultimate_scraper_support import scraper  # noqa: F401 — fixture for this module

FLARE_URL = "http://flaresolverr:8191/v1"


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_no_url(scraper: UltimateScraper):
    with patch("pry.core.settings.settings.flaresolverr_url", ""):
        result = await scraper._tier_flaresolverr("http://example.com", {})
        assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_success(scraper: UltimateScraper):
    respx.post(FLARE_URL).mock(
        return_value=httpx.Response(
            200, json={"solution": {"status": 200, "response": "<html>flare</html>"}}
        )
    )
    with patch("pry.core.settings.settings.flaresolverr_url", FLARE_URL):
        result = await scraper._tier_flaresolverr("http://example.com", {})
        assert result == "<html>flare</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_not_200(scraper: UltimateScraper):
    respx.post(FLARE_URL).mock(
        return_value=httpx.Response(200, json={"solution": {"status": 503, "response": "down"}})
    )
    with patch("pry.core.settings.settings.flaresolverr_url", FLARE_URL):
        result = await scraper._tier_flaresolverr("http://example.com", {})
        assert result is None
        result = await scraper._tier_flaresolverr("http://example.com", {})
        assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_surfaces_unsolved_reason(scraper: UltimateScraper, caplog):
    """Reachable sidecar (HTTP 200) that cannot solve must log its reason."""
    respx.post(FLARE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "error",
                "message": "Error solving the challenge. Timeout after 60.0 seconds.",
                "solution": {"status": 0, "response": ""},
            },
        )
    )
    with (
        patch("pry.core.settings.settings.flaresolverr_url", FLARE_URL),
        caplog.at_level("DEBUG", logger="pry.engine.tiers_http"),
    ):
        result = await scraper._tier_flaresolverr("http://example.com", {})
    assert result is None
    assert any("flaresolverr_unsolved" in r.message for r in caplog.records)


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_surfaces_http_error(scraper: UltimateScraper, caplog):
    """A non-2xx response from the sidecar must log the status, not vanish."""
    respx.post(FLARE_URL).mock(return_value=httpx.Response(500, text="internal error"))
    with (
        patch("pry.core.settings.settings.flaresolverr_url", FLARE_URL),
        caplog.at_level("DEBUG", logger="pry.engine.tiers_http"),
    ):
        result = await scraper._tier_flaresolverr("http://example.com", {})
    assert result is None
    assert any("flaresolverr_http_error" in r.message for r in caplog.records)
