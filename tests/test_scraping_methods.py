# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for scraping_methods — hidden-API discovery, session persistence, render-wait.

All tests are offline: httpx traffic uses ``httpx.MockTransport`` and browser
tiers use fake Playwright / Camoufox objects. No live network or browser.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from scraping_methods import METHODS, PersistentSession, discover_json_api, fetch_rendered

# ── Fixtures / fakes ───────────────────────────────────────────────────────

FIXTURE_HTML = """<!DOCTYPE html><html><head>
<script src="/static/app.js"></script>
<script src="https://cdn.example.com/lib.min.js"></script>
<script>
  fetch('/api/products?page=1');
  axios.get('/api/v2/odds');
  axios({ url: '/api/config' });
  const r = new XMLHttpRequest();
  r.open('GET', '/api/live/score');
  $.getJSON('/api/standings');
  const cfg = { apiUrl: '/api/root' };
</script>
</head><body></body></html>"""


class FakeResponse:
    """Minimal playwright response stub carrying a JSON body."""

    def __init__(self, body: str, content_type: str = "application/json") -> None:
        self.body = body
        self.headers = {"content-type": content_type}

    async def text(self) -> str:
        return self.body


class FakePage:
    """Minimal playwright page stub that fires ``response`` handlers on goto."""

    def __init__(self, content_html: str, responses: list[FakeResponse]) -> None:
        self.content_html = content_html
        self.responses = responses
        self.handlers: dict[str, Any] = {}
        self.goto_url: str | None = None

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.goto_url = url
        handler = self.handlers.get("response")
        if handler is not None:
            for resp in self.responses:
                await handler(resp)

    async def wait_for_load_state(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def wait_for_selector(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def wait_for_timeout(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def content(self) -> str:
        return self.content_html


def _fake_playwright(
    page_content: str = "<html>rendered</html>",
    *,
    json_responses: list[FakeResponse] | None = None,
    launch_error: Exception | None = None,
) -> MagicMock:
    """Build a fake ``async_playwright`` factory for ``async with`` use."""
    page = FakePage(page_content, json_responses or [])
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    launch = (
        AsyncMock(side_effect=launch_error) if launch_error else AsyncMock(return_value=browser)
    )
    pw = MagicMock()
    pw.chromium.launch = launch
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=pw)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _ok_handler() -> Any:
    """MockTransport handler: warm home page + JSON API responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                text="<html>home</html>",
                headers={"set-cookie": "sid=abc123; Path=/; HttpOnly"},
            )
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    return handler


# ── Hidden-API discovery ────────────────────────────────────────────────────


def test_discover_inline_api_endpoints() -> None:
    urls = discover_json_api("https://example.com/shop/items", FIXTURE_HTML)
    assert "https://example.com/api/products?page=1" in urls
    assert "https://example.com/api/v2/odds" in urls
    assert "https://example.com/api/config" in urls
    assert "https://example.com/api/live/score" in urls
    assert "https://example.com/api/standings" in urls
    assert "https://example.com/api/root" in urls


def test_discover_script_bundles() -> None:
    urls = discover_json_api("https://example.com/shop/items", FIXTURE_HTML)
    assert "https://example.com/static/app.js" in urls
    assert "https://cdn.example.com/lib.min.js" in urls


def test_discover_json_suffix() -> None:
    html = '<script>fetch("/data/feed.json?v=2")</script>'
    urls = discover_json_api("https://example.com/", html)
    assert "https://example.com/data/feed.json?v=2" in urls


def test_discover_dedupes() -> None:
    html = '<script>fetch("/api/x"); axios.get("/api/x")</script>'
    urls = discover_json_api("https://example.com/", html)
    assert urls.count("https://example.com/api/x") == 1


def test_discover_absolute_urls_preserved() -> None:
    html = '<script>fetch("https://api.other.com/data.json")</script>'
    urls = discover_json_api("https://example.com/", html)
    assert "https://api.other.com/data.json" in urls


def test_discover_ignores_junk() -> None:
    html = '<a href="#home">x</a><script>const u = "javascript:void(0)";</script>'
    assert discover_json_api("https://example.com/", html) == []


@pytest.mark.parametrize("html", ["", "<html></html>", "garbage", "fetch(", "no quotes here"])
def test_discover_never_raises(html: str) -> None:
    assert isinstance(discover_json_api("https://example.com/", html), list)


def test_discover_non_string_input() -> None:
    assert discover_json_api("https://example.com/", 12345) == []  # type: ignore[arg-type]
    assert discover_json_api(None, "<html></html>") == []  # type: ignore[arg-type]


# ── Session persistence / cookie warmer ─────────────────────────────────────


async def test_session_warmup_then_cookie_reuse() -> None:
    seen: list[httpx.Request] = []
    handler = _ok_handler()

    def tracking_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async with PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(tracking_handler)
    ) as session:
        resp = await session.fetch("https://example.com/api/products")
    assert resp is not None
    assert resp.json() == {"ok": True}
    assert session.is_warmed
    # Warm-up hit the homepage first.
    assert seen[0].url.scheme == "https"
    assert seen[0].url.host == "example.com"
    assert seen[0].url.path == "/"
    # Cookie collected during warm-up was sent on the API request.
    assert "sid=abc123" in (seen[-1].headers.get("cookie") or "")


async def test_session_reuses_cookies_across_calls() -> None:
    seen: list[httpx.Request] = []
    handler = _ok_handler()

    def tracking_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    session = PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(tracking_handler)
    )
    try:
        first = await session.fetch("https://example.com/api/a")
        second = await session.fetch("https://example.com/api/b")
        assert first is not None
        assert second is not None
        assert len(seen) == 3  # warmup + 2 API calls on ONE client
        assert all("sid=abc123" in (r.headers.get("cookie") or "") for r in seen[1:])
    finally:
        await session.close()


async def test_session_derives_home_from_first_fetch() -> None:
    seen: list[httpx.Request] = []
    handler = _ok_handler()

    def tracking_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    session = PersistentSession(transport=httpx.MockTransport(tracking_handler))
    try:
        resp = await session.fetch("https://example.com/api/v2/odds?market=ml")
        assert resp is not None
        assert seen[0].url.path == "/"  # derived homepage warm-up
        assert seen[-1].url.path == "/api/v2/odds"
        assert "sid=abc123" in (seen[-1].headers.get("cookie") or "")
    finally:
        await session.close()


async def test_session_warmup_failure_still_fetches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            raise httpx.ConnectError("no route to host", request=request)
        return httpx.Response(200, json={"ok": True})

    session = PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(handler)
    )
    try:
        assert await session.warmup() is False
        assert not session.is_warmed
        resp = await session.fetch("https://example.com/api/products")
        assert resp is not None
        assert resp.json() == {"ok": True}
    finally:
        await session.close()


async def test_session_never_raises_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    session = PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(handler)
    )
    try:
        assert await session.warmup() is False
        assert await session.fetch("https://example.com/api/products") is None
    finally:
        await session.close()


async def test_session_invalid_url_returns_none() -> None:
    session = PersistentSession(home_url="https://example.com/")
    try:
        assert await session.fetch("file:///etc/passwd") is None
        assert await session.fetch("") is None
    finally:
        await session.close()


async def test_session_cookies_snapshot() -> None:
    session = PersistentSession(
        home_url="https://example.com/", transport=httpx.MockTransport(_ok_handler())
    )
    try:
        assert session.cookies() == {}
        await session.warmup()
        assert session.cookies().get("sid") == "abc123"
    finally:
        await session.close()


# ── Render-wait (JS SPA) ────────────────────────────────────────────────────


async def test_fetch_rendered_playwright_html() -> None:
    fake_pw = _fake_playwright(page_content="<html>rendered</html>")
    with (
        patch("scraping_methods._HAS_PLAYWRIGHT", True),
        patch("scraping_methods.async_playwright", fake_pw),
    ):
        html = await fetch_rendered("https://example.com/spa")
    assert html == "<html>rendered</html>"


async def test_fetch_rendered_collect_json() -> None:
    fake_pw = _fake_playwright(
        page_content="<html>shell</html>",
        json_responses=[FakeResponse('{"odds":[1,2]}', "application/json")],
    )
    with (
        patch("scraping_methods._HAS_PLAYWRIGHT", True),
        patch("scraping_methods.async_playwright", fake_pw),
    ):
        result = await fetch_rendered("https://example.com/spa", collect_json=True)
    assert result is not None
    assert "odds" in result


async def test_fetch_rendered_selector_wait() -> None:
    fake_pw = _fake_playwright(page_content="<html>loaded</html>")
    with (
        patch("scraping_methods._HAS_PLAYWRIGHT", True),
        patch("scraping_methods.async_playwright", fake_pw),
    ):
        html = await fetch_rendered("https://example.com/spa", selector="#content")
    assert html == "<html>loaded</html>"


async def test_fetch_rendered_never_raises_on_launch_failure() -> None:
    fake_pw = _fake_playwright(launch_error=OSError("no browser binary"))
    with (
        patch("scraping_methods._HAS_PLAYWRIGHT", True),
        patch("scraping_methods.async_playwright", fake_pw),
    ):
        result = await fetch_rendered("https://example.com/spa")
    assert result is None


async def test_fetch_rendered_missing_browser_returns_none() -> None:
    with (
        patch("scraping_methods._HAS_PLAYWRIGHT", False),
        patch("scraping_methods._HAS_CAMOUFOX", False),
        patch("scraping_methods._HAS_CAMOUFOX_INTEGRATION", False),
    ):
        assert await fetch_rendered("https://example.com/spa") is None


async def test_fetch_rendered_camoufox_package() -> None:
    fake = MagicMock()
    fake.new_page = AsyncMock(return_value=FakePage("<html>camoufox</html>", []))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake)
    cm.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("scraping_methods._HAS_CAMOUFOX", True),
        patch("scraping_methods.AsyncCamoufox", MagicMock(return_value=cm)),
    ):
        html = await fetch_rendered("https://example.com/spa", prefer="camoufox")
    assert html == "<html>camoufox</html>"


async def test_fetch_rendered_camoufox_wrapper_fallback() -> None:
    fake_browser = MagicMock()
    fake_browser.fetch = AsyncMock(
        return_value={"success": True, "content": "<html>wrapper</html>"}
    )
    with (
        patch("scraping_methods._HAS_CAMOUFOX", False),
        patch("scraping_methods._HAS_CAMOUFOX_INTEGRATION", True),
        patch("scraping_methods.CamoufoxBrowser", MagicMock(return_value=fake_browser)),
    ):
        html = await fetch_rendered("https://example.com/spa", prefer="camoufox")
    assert html == "<html>wrapper</html>"


async def test_fetch_rendered_invalid_url_returns_none() -> None:
    assert await fetch_rendered("file:///etc/passwd") is None


# ── Registry ────────────────────────────────────────────────────────────────


def test_methods_registry() -> None:
    assert set(METHODS) == {"hidden_api_discovery", "persistent_session", "render_wait"}
    for key, meta in METHODS.items():
        assert meta["name"], key
        assert meta["when"], key
        assert callable(meta["callable"]), key
    assert METHODS["hidden_api_discovery"]["callable"] is discover_json_api
    assert METHODS["persistent_session"]["callable"] is PersistentSession
    assert METHODS["render_wait"]["callable"] is fetch_rendered
