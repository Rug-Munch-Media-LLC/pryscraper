# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for scraping_methods — render-wait (JS SPA) tiers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from pry.engine.scraping_methods import fetch_rendered
from tests.support.scraping import FakePage, FakeResponse, fake_playwright


async def test_fetch_rendered_playwright_html() -> None:
    fake_pw = fake_playwright(page_content="<html>rendered</html>")
    with (
        patch("pry.engine.methods._common._HAS_PLAYWRIGHT", True),
        patch("pry.engine.methods._common.async_playwright", fake_pw),
    ):
        html = await fetch_rendered("https://example.com/spa")
    assert html == "<html>rendered</html>"


async def test_fetch_rendered_collect_json() -> None:
    fake_pw = fake_playwright(
        page_content="<html>shell</html>",
        json_responses=[FakeResponse('{"odds":[1,2]}', "application/json")],
    )
    with (
        patch("pry.engine.methods._common._HAS_PLAYWRIGHT", True),
        patch("pry.engine.methods._common.async_playwright", fake_pw),
    ):
        result = await fetch_rendered("https://example.com/spa", collect_json=True)
    assert result is not None
    assert "odds" in result


async def test_fetch_rendered_selector_wait() -> None:
    fake_pw = fake_playwright(page_content="<html>loaded</html>")
    with (
        patch("pry.engine.methods._common._HAS_PLAYWRIGHT", True),
        patch("pry.engine.methods._common.async_playwright", fake_pw),
    ):
        html = await fetch_rendered("https://example.com/spa", selector="#content")
    assert html == "<html>loaded</html>"


async def test_fetch_rendered_never_raises_on_launch_failure() -> None:
    fake_pw = fake_playwright(launch_error=OSError("no browser binary"))
    with (
        patch("pry.engine.methods._common._HAS_PLAYWRIGHT", True),
        patch("pry.engine.methods._common.async_playwright", fake_pw),
    ):
        result = await fetch_rendered("https://example.com/spa")
    assert result is None


async def test_fetch_rendered_missing_browser_returns_none() -> None:
    with (
        patch("pry.engine.methods._common._HAS_PLAYWRIGHT", False),
        patch("pry.engine.methods._common._HAS_CAMOUFOX", False),
        patch("pry.engine.methods._common._HAS_CAMOUFOX_INTEGRATION", False),
    ):
        assert await fetch_rendered("https://example.com/spa") is None


async def test_fetch_rendered_camoufox_package() -> None:
    fake = MagicMock()
    fake.new_page = AsyncMock(return_value=FakePage("<html>camoufox</html>", []))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake)
    cm.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("pry.engine.methods._common._HAS_CAMOUFOX", True),
        patch("pry.engine.methods._common.AsyncCamoufox", MagicMock(return_value=cm)),
    ):
        html = await fetch_rendered("https://example.com/spa", prefer="camoufox")
    assert html == "<html>camoufox</html>"


async def test_fetch_rendered_camoufox_wrapper_fallback() -> None:
    fake_browser = MagicMock()
    fake_browser.fetch = AsyncMock(
        return_value={"success": True, "content": "<html>wrapper</html>"}
    )
    with (
        patch("pry.engine.methods._common._HAS_CAMOUFOX", False),
        patch("pry.engine.methods._common._HAS_CAMOUFOX_INTEGRATION", True),
        patch("pry.engine.methods._common.CamoufoxBrowser", MagicMock(return_value=fake_browser)),
    ):
        html = await fetch_rendered("https://example.com/spa", prefer="camoufox")
    assert html == "<html>wrapper</html>"


async def test_fetch_rendered_invalid_url_returns_none() -> None:
    assert await fetch_rendered("file:///etc/passwd") is None
