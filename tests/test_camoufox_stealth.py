# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Camoufox fetch_with_stealth: human-behaviour scrolling and failure paths."""

import sys
from unittest.mock import patch

from pry.engine import camoufox_integration
from pry.engine.camoufox_integration import CamoufoxBrowser
from tests.camoufox_support import (  # noqa: F401 - helpers and fixtures
    _fake_camoufox_module,
    _mock_camoufox_browser,
    _reset_camoufox_pool,
)


async def test_fetch_with_stealth_scrolls_and_returns_content() -> None:
    first = _mock_camoufox_browser(content="<html>first</html>")
    second = _mock_camoufox_browser(content="<html>after-scroll</html>")
    browser2 = second.__aenter__.return_value

    fake_mod = _fake_camoufox_module(second)
    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=first),
        patch.dict(sys.modules, {"camoufox": fake_mod}),
    ):
        result = await CamoufoxBrowser(default_profile="chrome_mac").fetch_with_stealth(
            "https://example.com",
            human_behavior={"scroll": [0, 500, 1000], "wait_time": 1200},
        )

    assert result["success"] is True
    assert result["content"] == "<html>after-scroll</html>"
    scroll_calls = [c.args[0] for c in browser2.evaluate.await_args_list]
    expected = [
        "window.scrollTo(0, 0)",
        "window.scrollTo(0, 500)",
        "window.scrollTo(0, 1000)",
    ]
    assert scroll_calls == expected
    browser2.wait_for_timeout.assert_awaited_with(1200)


async def test_fetch_with_stealth_without_human_behavior_keeps_first_content() -> None:
    first = _mock_camoufox_browser(content="<html>first</html>")

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=first),
    ):
        result = await CamoufoxBrowser().fetch_with_stealth("https://example.com")

    assert result["success"] is True
    assert result["content"] == "<html>first</html>"


async def test_fetch_with_stealth_returns_early_on_failure() -> None:
    with (
        patch.object(camoufox_integration, "_has_camoufox", False),
    ):
        result = await CamoufoxBrowser().fetch_with_stealth("https://example.com")

    assert result["success"] is False
    assert "camoufox" in result["error"]
