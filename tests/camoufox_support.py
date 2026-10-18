# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared fixtures and doubles for the Camoufox integration tests.

``camoufox`` is an optional dependency and is NOT installed in the test venv,
so the module-level ``_has_camoufox`` flag is False and ``AsyncCamoufox`` is
never bound as a module attribute. Success paths patch
``camoufox_integration.AsyncCamoufox`` with ``create=True`` — no real browser
is launched and no network access happens.
"""

import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from pry.engine import camoufox_pool


@pytest.fixture(autouse=True)
def _reset_camoufox_pool() -> None:
    """Reset the process-level pooled Camoufox browser between tests.

    The pool is a lazy singleton owned by ``camoufox_pool`` (the integration
    module only re-exports ``close_browsers``); without a reset a mocked
    browser cached by one test leaks into the next and breaks isolation.
    """
    camoufox_pool._pooled_camoufox = None
    camoufox_pool._pooled_camoufox_config = None


def _mock_camoufox_browser(
    content: str = "<html>camoufox</html>", title: str = "Camoufox"
) -> MagicMock:
    """Build a mocked AsyncCamoufox chain returning canned page content."""
    browser = MagicMock()
    browser.new_page = AsyncMock(return_value=browser)
    browser.route = AsyncMock()  # SSRF route guard registration
    browser.context.add_cookies = AsyncMock()
    browser.goto = AsyncMock()
    browser.evaluate = AsyncMock()
    browser.wait_for_selector = AsyncMock()
    browser.wait_for_timeout = AsyncMock()
    browser.content = AsyncMock(return_value=content)
    browser.title = AsyncMock(return_value=title)
    browser.context.cookies = AsyncMock(return_value=[{"name": "cf", "value": "v"}])

    mock_cls = AsyncMock()
    mock_cls.__aenter__.return_value = browser
    mock_cls.__aexit__.return_value = False
    return mock_cls


class _FakeRoute:
    """Minimal Playwright route double for exercising the guard directly."""

    def __init__(self, url: str) -> None:
        self.request = types.SimpleNamespace(url=url)
        self.aborted = False
        self.continued = False

    async def abort(self) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


def _fake_camoufox_module(async_cls: MagicMock) -> types.ModuleType:
    """Build a fake `camoufox` module so the local `from camoufox import
    AsyncCamoufox` inside fetch_with_stealth resolves to our mock.

    Mirrors how fetch() patches the attribute: `AsyncCamoufox(**config)` must
    return the async context manager synchronously (a plain MagicMock), then
    `async with` drives `__aenter__` on it.
    """
    mod = types.ModuleType("camoufox")
    mod.AsyncCamoufox = MagicMock(return_value=async_cls)  # type: ignore[attr-defined]
    return mod
