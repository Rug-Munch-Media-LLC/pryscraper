# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the browser-action dispatcher (pry.engine.actions).

Added alongside the execute_action P2 refactor (dispatch-table extraction):
the module previously had no direct tests. A FakePage records calls so the
dispatch behaviour and every guard clause are pinned without Playwright.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from pry.engine.actions import execute_action


class FakePage:
    """Records awaited page calls; every method returns an awaitable."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.keyboard = Mock()
        self.keyboard.press = AsyncMock()

    def _record(self, name: str):
        async def _fn(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return _fn

    def __getattr__(self, name: str):
        # click, fill, evaluate, wait_for_selector, screenshot,
        # select_option, check, uncheck, hover, focus — all become recorders.
        return self._record(name)


@pytest.mark.asyncio
async def test_non_dict_action_returns_false() -> None:
    assert await execute_action(FakePage(), "click") is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_unknown_action_type_returns_false() -> None:
    assert await execute_action(FakePage(), {"type": "teleport"}) is False


@pytest.mark.asyncio
async def test_click_requires_selector() -> None:
    page = FakePage()
    assert await execute_action(page, {"type": "click"}) is False
    assert await execute_action(page, {"type": "click", "selector": "#go"}) is True
    assert (
        page.calls == [("click", ("#go",), {"timeout": pytest.approx(30_000)})]
        or page.calls[0][0] == "click"
    )


@pytest.mark.asyncio
async def test_type_requires_selector_and_text() -> None:
    page = FakePage()
    assert await execute_action(page, {"type": "type", "selector": "#f"}) is False
    assert await execute_action(page, {"type": "type", "text": "hi"}) is False
    assert await execute_action(page, {"type": "type", "selector": "#f", "text": "hi"}) is True
    assert page.calls[0][0] == "fill"
    expected = ("#f", "hi")
    assert page.calls[0][1] == expected


@pytest.mark.asyncio
async def test_scroll_defaults_down_and_supports_up() -> None:
    page = FakePage()
    assert await execute_action(page, {"type": "scroll"}) is True
    assert await execute_action(page, {"type": "scroll", "direction": "up", "amount": 100}) is True
    scripts = [c[1][0] for c in page.calls if c[0] == "evaluate"]
    assert "window.scrollBy(0, 500)" in scripts
    assert "window.scrollBy(0, -100)" in scripts


@pytest.mark.asyncio
async def test_wait_selector_ms_and_failure() -> None:
    page = FakePage()
    assert await execute_action(page, {"type": "wait", "selector": "#spinner"}) is True
    assert await execute_action(page, {"type": "wait", "ms": 10}) is True
    assert await execute_action(page, {"type": "wait"}) is False


@pytest.mark.asyncio
async def test_press_requires_key() -> None:
    page = FakePage()
    assert await execute_action(page, {"type": "press"}) is False
    assert await execute_action(page, {"type": "press", "key": "Enter"}) is True
    page.keyboard.press.assert_awaited_once_with("Enter")


@pytest.mark.asyncio
async def test_screenshot_always_succeeds() -> None:
    page = FakePage()
    assert await execute_action(page, {"type": "screenshot"}) is True
    assert page.calls[0][0] == "screenshot"


@pytest.mark.asyncio
async def test_evaluate_requires_script() -> None:
    page = FakePage()
    assert await execute_action(page, {"type": "evaluate"}) is False
    assert await execute_action(page, {"type": "evaluate", "script": "1+1"}) is True


@pytest.mark.asyncio
async def test_select_requires_selector_and_value() -> None:
    page = FakePage()
    assert await execute_action(page, {"type": "select", "selector": "#s"}) is False
    assert await execute_action(page, {"type": "select", "value": "v"}) is False
    assert await execute_action(page, {"type": "select", "selector": "#s", "value": "v"}) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("action_type", ["check", "uncheck", "hover", "focus"])
async def test_selector_actions_require_selector(action_type: str) -> None:
    page = FakePage()
    assert await execute_action(page, {"type": action_type}) is False
    assert await execute_action(page, {"type": action_type, "selector": "#el"}) is True
    assert any(c[0] == action_type for c in page.calls)


@pytest.mark.asyncio
async def test_exceptions_never_propagate() -> None:
    class ExplodingPage(FakePage):
        def __getattr__(self, name: str):
            async def _boom(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError("browser died")

            return _boom

    assert await execute_action(ExplodingPage(), {"type": "click", "selector": "#x"}) is False
