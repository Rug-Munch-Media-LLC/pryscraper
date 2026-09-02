# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for Camoufox integration: launch-arg construction, profile fallback,
cookie injection, wait behavior, and human-behavior scrolling.

``camoufox`` is an optional dependency and is NOT installed in the test venv,
so the module-level ``_has_camoufox`` flag is False and ``AsyncCamoufox`` is
never bound as a module attribute. The success paths are exercised by patching
``camoufox_integration.AsyncCamoufox`` with ``create=True`` — no real browser
is launched and no network access happens.
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pry.engine import camoufox_integration
from pry.engine.camoufox_integration import CamoufoxBrowser

# ── Profile catalog / launch-arg construction ───────────────────


@pytest.fixture(autouse=True)
def _reset_camoufox_pool() -> None:
    """Reset the module-level pooled Camoufox browser between tests.

    The pool is a lazy singleton; without a reset a mocked browser cached by
    one test would leak into the next and break isolation.
    """
    camoufox_integration._pooled_camoufox = None
    camoufox_integration._pooled_camoufox_config = None


def test_default_configs_launch_args_shape() -> None:
    for _name, cfg in CamoufoxBrowser.DEFAULT_CONFIGS.items():
        assert cfg["headless"] is True
        assert cfg["os"] in {"windows", "macos", "linux"}
        assert cfg["browser"] in {"chrome", "firefox"}
        assert isinstance(cfg["screen"], tuple)
        assert len(cfg["screen"]) == 2
        assert isinstance(cfg["window"], tuple)
        assert len(cfg["window"]) == 2


def test_default_profile_is_valid() -> None:
    b = CamoufoxBrowser()
    assert b.default_profile in CamoufoxBrowser.DEFAULT_CONFIGS


def test_list_profiles_matches_catalog() -> None:
    assert set(CamoufoxBrowser.list_profiles()) == set(CamoufoxBrowser.DEFAULT_CONFIGS.keys())


def test_is_available_reflects_camoufox_installed() -> None:
    with patch.object(camoufox_integration, "_has_camoufox", True):
        assert CamoufoxBrowser().is_available() is True
    with patch.object(camoufox_integration, "_has_camoufox", False):
        assert CamoufoxBrowser().is_available() is False


# ── fetch() ─────────────────────────────────────────────────────


async def test_fetch_returns_error_when_camoufox_missing() -> None:
    with patch.object(camoufox_integration, "_has_camoufox", False):
        result = await CamoufoxBrowser().fetch("https://example.com")
    assert result["success"] is False
    assert "camoufox" in result["error"]


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


async def test_fetch_builds_launch_args_from_profile() -> None:
    mock_cls = _mock_camoufox_browser()
    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch(
            "pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls
        ) as mock_camoufox,
    ):
        result = await CamoufoxBrowser(default_profile="chrome_windows").fetch(
            "https://example.com"
        )

    assert result["success"] is True
    assert result["profile"] == "chrome_windows"
    assert result["title"] == "Camoufox"
    launch_kwargs = mock_camoufox.call_args.kwargs
    assert launch_kwargs["os"] == "windows"
    assert launch_kwargs["browser"] == "chrome"
    assert launch_kwargs["screen"] == (1920, 1080)
    assert launch_kwargs["headless"] is True
    # No proxy → not passed through
    assert "proxy" not in launch_kwargs


async def test_fetch_adds_proxy_to_launch_args() -> None:
    mock_cls = _mock_camoufox_browser()
    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch(
            "pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls
        ) as mock_camoufox,
    ):
        result = await CamoufoxBrowser(default_profile="firefox_linux").fetch(
            "https://example.com", proxy="http://user:pass@proxy.example:8080"
        )

    assert result["success"] is True
    launch_kwargs = mock_camoufox.call_args.kwargs
    assert launch_kwargs["os"] == "linux"
    assert launch_kwargs["proxy"] == "http://user:pass@proxy.example:8080"


async def test_fetch_unknown_profile_falls_back_to_chrome_windows() -> None:
    mock_cls = _mock_camoufox_browser()
    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch(
            "pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls
        ) as mock_camoufox,
    ):
        result = await CamoufoxBrowser().fetch("https://example.com", profile="does-not-exist")

    assert result["success"] is True
    assert result["profile"] == "does-not-exist"  # echoes requested profile
    launch_kwargs = mock_camoufox.call_args.kwargs
    assert launch_kwargs["os"] == "windows"  # falls back to chrome_windows config
    assert launch_kwargs["browser"] == "chrome"


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


async def test_fetch_exception_returns_error_dict() -> None:
    mock_cls = _mock_camoufox_browser()
    mock_cls.__aenter__.return_value.goto.side_effect = RuntimeError("firefox crashed")

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls),
    ):
        result = await CamoufoxBrowser().fetch("https://example.com")

    assert result["success"] is False
    assert "firefox crashed" in result["error"]


# ── fetch() SSRF validation & redirect re-validation ────────────


async def test_fetch_rejects_private_url_before_navigation() -> None:
    """The initial URL must be SSRF-validated before the browser navigates."""
    mock_cls = _mock_camoufox_browser()
    browser = mock_cls.__aenter__.return_value

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls),
    ):
        result = await CamoufoxBrowser().fetch("http://169.254.169.254/latest/meta-data/")

    assert result["success"] is False
    browser.goto.assert_not_awaited()


async def test_fetch_installs_ssrf_route_guard() -> None:
    """The per-request route guard must be installed before navigation so the
    browser's internal redirect hops are re-validated too."""
    mock_cls = _mock_camoufox_browser()
    browser = mock_cls.__aenter__.return_value

    with (
        patch.object(camoufox_integration, "_has_camoufox", True),
        patch("pry.engine.camoufox_integration.AsyncCamoufox", create=True, return_value=mock_cls),
    ):
        result = await CamoufoxBrowser().fetch("https://example.com")

    assert result["success"] is True
    browser.route.assert_awaited_once()


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


async def test_guarded_route_aborts_metadata_request() -> None:
    route = _FakeRoute("http://169.254.169.254/latest/meta-data/")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is True
    assert route.continued is False


async def test_guarded_route_aborts_loopback_request() -> None:
    route = _FakeRoute("http://127.0.0.1:8080/admin")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is True
    assert route.continued is False


async def test_guarded_route_aborts_internal_hostname() -> None:
    route = _FakeRoute("http://kubernetes.default.svc.cluster.local/")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is True
    assert route.continued is False


async def test_guarded_route_continues_public_request() -> None:
    route = _FakeRoute("https://example.com/")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is False
    assert route.continued is True


async def test_guarded_route_continues_non_network_scheme() -> None:
    """data:/blob: URLs never touch the network — no SSRF surface, continue."""
    route = _FakeRoute("data:text/html,<h1>hi</h1>")
    await CamoufoxBrowser()._guarded_route(route)
    assert route.aborted is False
    assert route.continued is True


# ── fetch_with_stealth ──────────────────────────────────────────


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
    assert scroll_calls == [
        "window.scrollTo(0, 0)",
        "window.scrollTo(0, 500)",
        "window.scrollTo(0, 1000)",
    ]
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
