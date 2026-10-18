# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Camoufox cookie injection and wait behaviour before content extraction."""

from unittest.mock import patch

from pry.engine import camoufox_integration
from pry.engine.camoufox_integration import CamoufoxBrowser
from tests.camoufox_support import (  # noqa: F401 - helpers and fixtures
    _mock_camoufox_browser,
    _reset_camoufox_pool,
)


async def test_fetch_injects_cookies_before_goto() -> None:
    mock_cls = _mock_camoufox_browser()
    browser = mock_cls.__aenter__.return_value
    cookies = [{"name": "a", "value": "b", "domain": ".example.com", "path": "/"}]

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls),
    ):
        await CamoufoxBrowser().fetch("https://example.com", cookies=cookies)

    browser.context.add_cookies.assert_awaited_once_with(cookies)


async def test_fetch_uses_wait_selector_when_provided() -> None:
    mock_cls = _mock_camoufox_browser()
    browser = mock_cls.__aenter__.return_value

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls),
    ):
        await CamoufoxBrowser().fetch(
            "https://example.com", wait_selector="#content", wait_time=5000
        )

    browser.wait_for_selector.assert_awaited_once_with("#content", timeout=5000)
    browser.wait_for_timeout.assert_not_awaited()


async def test_fetch_uses_wait_timeout_when_no_selector() -> None:
    mock_cls = _mock_camoufox_browser()
    browser = mock_cls.__aenter__.return_value

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls),
    ):
        await CamoufoxBrowser().fetch("https://example.com", wait_time=2500)

    browser.wait_for_timeout.assert_awaited_once_with(2500)
    browser.wait_for_selector.assert_not_awaited()
