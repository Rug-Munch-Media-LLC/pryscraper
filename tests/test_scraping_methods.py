# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for scraping_methods — hidden-API discovery, session persistence,
render-wait, feed parsing, sitemap discovery, GraphQL, paginated crawl.

All tests are offline: httpx traffic uses ``httpx.MockTransport`` (or a
patched ``_sync_get`` / ``_sync_post``) and browser tiers use fake Playwright
/ Camoufox objects. No live network or browser.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pry.engine.scraping_methods import (
    METHODS,
    PersistentSession,
    discover_feed,
    discover_graphql,
    discover_json_api,
    discover_sitemap,
    fetch_rendered,
    paginated_fetch,
    parse_feed,
    parse_sitemap,
    query_graphql,
)

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

RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <link>https://example.com/</link>
    <description>Test channel</description>
    <item>
      <title>First post</title>
      <link>https://example.com/posts/1</link>
      <description>Summary one</description>
      <pubDate>Mon, 17 Aug 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second post</title>
      <link>https://example.com/posts/2</link>
      <description>Summary two</description>
      <pubDate>Tue, 18 Aug 2026 11:30:00 GMT</pubDate>
    </item>
    <item>
      <title>No extras</title>
      <link>https://example.com/posts/3</link>
    </item>
  </channel>
</rss>"""

ATOM_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom Feed</title>
  <link href="https://example.com/"/>
  <entry>
    <title>Atom entry one</title>
    <link href="https://example.com/entries/1"/>
    <summary>Atom summary one</summary>
    <published>2026-08-17T10:00:00Z</published>
  </entry>
  <entry>
    <title>Atom entry two</title>
    <link href="https://example.com/entries/2"/>
    <content type="html">&lt;p&gt;Content two&lt;/p&gt;</content>
    <updated>2026-08-18T11:30:00Z</updated>
  </entry>
</feed>"""

FEED_LINK_HTML = """<html><head>
<link rel="alternate" type="application/rss+xml" title="Posts" href="/feed.xml">
<link rel="stylesheet" href="/styles.css">
</head></html>"""

SITEMAP_INDEX_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-posts.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
</sitemapindex>"""

SITEMAP_URLSET_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/posts/1</loc></url>
</urlset>"""

SITEMAP_PAGES_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/pages/2</loc></url>
</urlset>"""

ROBOTS_TXT = """User-agent: *
Disallow: /private
Sitemap: https://example.com/sitemap.xml
"""

GRAPHQL_HTML = """<!DOCTYPE html><html><head>
<script src="/static/app.js"></script>
<script src="https://cdn.example.com/graphql-client.js"></script>
<script>
  const uri = "/api/graphql";
  fetch("/graphql", { method: "POST" });
  window.__APOLLO_STATE__ = { ROOT_QUERY: {} };
</script>
</head><body>
<div data-hasura-role="public"></div>
</body></html>"""


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
        patch("pry.engine.scraping_methods._HAS_PLAYWRIGHT", True),
        patch("pry.engine.scraping_methods.async_playwright", fake_pw),
    ):
        html = await fetch_rendered("https://example.com/spa")
    assert html == "<html>rendered</html>"


async def test_fetch_rendered_collect_json() -> None:
    fake_pw = _fake_playwright(
        page_content="<html>shell</html>",
        json_responses=[FakeResponse('{"odds":[1,2]}', "application/json")],
    )
    with (
        patch("pry.engine.scraping_methods._HAS_PLAYWRIGHT", True),
        patch("pry.engine.scraping_methods.async_playwright", fake_pw),
    ):
        result = await fetch_rendered("https://example.com/spa", collect_json=True)
    assert result is not None
    assert "odds" in result


async def test_fetch_rendered_selector_wait() -> None:
    fake_pw = _fake_playwright(page_content="<html>loaded</html>")
    with (
        patch("pry.engine.scraping_methods._HAS_PLAYWRIGHT", True),
        patch("pry.engine.scraping_methods.async_playwright", fake_pw),
    ):
        html = await fetch_rendered("https://example.com/spa", selector="#content")
    assert html == "<html>loaded</html>"


async def test_fetch_rendered_never_raises_on_launch_failure() -> None:
    fake_pw = _fake_playwright(launch_error=OSError("no browser binary"))
    with (
        patch("pry.engine.scraping_methods._HAS_PLAYWRIGHT", True),
        patch("pry.engine.scraping_methods.async_playwright", fake_pw),
    ):
        result = await fetch_rendered("https://example.com/spa")
    assert result is None


async def test_fetch_rendered_missing_browser_returns_none() -> None:
    with (
        patch("pry.engine.scraping_methods._HAS_PLAYWRIGHT", False),
        patch("pry.engine.scraping_methods._HAS_CAMOUFOX", False),
        patch("pry.engine.scraping_methods._HAS_CAMOUFOX_INTEGRATION", False),
    ):
        assert await fetch_rendered("https://example.com/spa") is None


async def test_fetch_rendered_camoufox_package() -> None:
    fake = MagicMock()
    fake.new_page = AsyncMock(return_value=FakePage("<html>camoufox</html>", []))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake)
    cm.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("pry.engine.scraping_methods._HAS_CAMOUFOX", True),
        patch("pry.engine.scraping_methods.AsyncCamoufox", MagicMock(return_value=cm)),
    ):
        html = await fetch_rendered("https://example.com/spa", prefer="camoufox")
    assert html == "<html>camoufox</html>"


async def test_fetch_rendered_camoufox_wrapper_fallback() -> None:
    fake_browser = MagicMock()
    fake_browser.fetch = AsyncMock(
        return_value={"success": True, "content": "<html>wrapper</html>"}
    )
    with (
        patch("pry.engine.scraping_methods._HAS_CAMOUFOX", False),
        patch("pry.engine.scraping_methods._HAS_CAMOUFOX_INTEGRATION", True),
        patch("pry.engine.scraping_methods.CamoufoxBrowser", MagicMock(return_value=fake_browser)),
    ):
        html = await fetch_rendered("https://example.com/spa", prefer="camoufox")
    assert html == "<html>wrapper</html>"


async def test_fetch_rendered_invalid_url_returns_none() -> None:
    assert await fetch_rendered("file:///etc/passwd") is None


# ── RSS/Atom feed parsing ───────────────────────────────────────────────────


def test_parse_rss_feed() -> None:
    fake = httpx.Response(200, text=RSS_FIXTURE)
    with patch("pry.engine.scraping_methods._sync_get", return_value=fake):
        entries = parse_feed("https://example.com/feed.xml")
    assert len(entries) == 3
    assert entries[0] == {
        "title": "First post",
        "link": "https://example.com/posts/1",
        "summary": "Summary one",
        "published": "Mon, 17 Aug 2026 10:00:00 GMT",
    }
    assert entries[1]["title"] == "Second post"
    # Fields absent from an item stay empty strings.
    assert entries[2] == {
        "title": "No extras",
        "link": "https://example.com/posts/3",
        "summary": "",
        "published": "",
    }


def test_parse_atom_feed() -> None:
    fake = httpx.Response(200, text=ATOM_FIXTURE)
    with patch("pry.engine.scraping_methods._sync_get", return_value=fake):
        entries = parse_feed("https://example.com/atom.xml")
    assert len(entries) == 2
    assert entries[0] == {
        "title": "Atom entry one",
        "link": "https://example.com/entries/1",
        "summary": "Atom summary one",
        "published": "2026-08-17T10:00:00Z",
    }
    # <content> falls back to summary; <updated> falls back to published.
    assert entries[1]["summary"] == "<p>Content two</p>"
    assert entries[1]["published"] == "2026-08-18T11:30:00Z"


def test_parse_feed_non_feed_xml_returns_empty() -> None:
    fake = httpx.Response(200, text="<html><body>not a feed</body></html>")
    with patch("pry.engine.scraping_methods._sync_get", return_value=fake):
        assert parse_feed("https://example.com/feed.xml") == []


def test_parse_feed_malformed_xml_returns_empty() -> None:
    fake = httpx.Response(200, text="<rss><channel>unclosed")
    with patch("pry.engine.scraping_methods._sync_get", return_value=fake):
        assert parse_feed("https://example.com/feed.xml") == []


def test_parse_feed_fetch_failure_returns_empty() -> None:
    with patch("pry.engine.scraping_methods._sync_get", return_value=None):
        assert parse_feed("https://example.com/feed.xml") == []


def test_parse_feed_invalid_input_no_network() -> None:
    assert parse_feed("") == []
    assert parse_feed(None) == []  # type: ignore[arg-type]
    assert parse_feed("file:///etc/passwd") == []


def test_discover_feed_rss_link() -> None:
    assert (
        discover_feed("https://example.com/blog", FEED_LINK_HTML) == "https://example.com/feed.xml"
    )


def test_discover_feed_atom_link() -> None:
    html = '<link rel="alternate" type="application/atom+xml" href="https://cdn.example.com/atom">'
    assert discover_feed("https://example.com/", html) == "https://cdn.example.com/atom"


def test_discover_feed_attr_order_insensitive() -> None:
    html = '<link type="application/rss+xml" rel="alternate" href="/rss">'
    assert discover_feed("https://example.com/", html) == "https://example.com/rss"


def test_discover_feed_returns_none_when_missing() -> None:
    assert discover_feed("https://example.com/", "<html><head></head></html>") is None
    assert discover_feed("https://example.com/", "") is None
    assert discover_feed("", "<html></html>") is None
    assert discover_feed("https://example.com/", None) is None  # type: ignore[arg-type]


# ── Sitemap-driven discovery ────────────────────────────────────────────────


def test_parse_sitemap_urlset() -> None:
    fake = httpx.Response(200, text=SITEMAP_URLSET_FIXTURE)
    with patch("pry.engine.scraping_methods._sync_get", return_value=fake) as mock_get:
        urls = parse_sitemap("https://example.com/sitemap.xml")
    assert urls == [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/posts/1",
    ]
    assert mock_get.call_count == 1


def test_parse_sitemap_index_recurses() -> None:
    index = httpx.Response(200, text=SITEMAP_INDEX_FIXTURE)
    posts = httpx.Response(200, text=SITEMAP_URLSET_FIXTURE)
    pages = httpx.Response(200, text=SITEMAP_PAGES_FIXTURE)
    with patch(
        "pry.engine.scraping_methods._sync_get", side_effect=[index, posts, pages]
    ) as mock_get:
        urls = parse_sitemap("https://example.com/sitemap.xml")
    assert mock_get.call_count == 3
    assert "https://example.com/about" in urls
    assert "https://example.com/pages/2" in urls
    assert len(urls) == 4  # 3 from posts + 1 from pages, de-duplicated


def test_parse_sitemap_self_reference_terminates() -> None:
    self_index = httpx.Response(
        200,
        text=(
            '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://example.com/sitemap.xml</loc></sitemap></sitemapindex>"
        ),
    )
    with patch("pry.engine.scraping_methods._sync_get", return_value=self_index) as mock_get:
        urls = parse_sitemap("https://example.com/sitemap.xml")
    assert urls == []
    assert mock_get.call_count == 1


def test_parse_sitemap_bad_xml_returns_empty() -> None:
    fake = httpx.Response(200, text="not xml at all")
    with patch("pry.engine.scraping_methods._sync_get", return_value=fake):
        assert parse_sitemap("https://example.com/sitemap.xml") == []


def test_parse_sitemap_fetch_failure_returns_empty() -> None:
    with patch("pry.engine.scraping_methods._sync_get", return_value=None):
        assert parse_sitemap("https://example.com/sitemap.xml") == []


def test_parse_sitemap_invalid_input_no_network() -> None:
    assert parse_sitemap("") == []
    assert parse_sitemap(None) == []  # type: ignore[arg-type]


def test_discover_sitemap_via_robots() -> None:
    fake = httpx.Response(200, text=ROBOTS_TXT)
    with patch("pry.engine.scraping_methods._sync_get", return_value=fake) as mock_get:
        found = discover_sitemap("https://example.com")
    assert found == "https://example.com/sitemap.xml"
    assert mock_get.call_count == 1
    assert mock_get.call_args.args == ("https://example.com/robots.txt",)


def test_discover_sitemap_robots_without_sitemap_line_falls_back() -> None:
    fake = httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
    with patch("pry.engine.scraping_methods._sync_get", return_value=fake):
        assert discover_sitemap("example.com") == "https://example.com/sitemap.xml"


def test_discover_sitemap_robots_unreachable_falls_back() -> None:
    with patch("pry.engine.scraping_methods._sync_get", return_value=None):
        assert discover_sitemap("https://example.com") == "https://example.com/sitemap.xml"


def test_discover_sitemap_invalid_domain() -> None:
    assert discover_sitemap("") is None
    assert discover_sitemap(None) is None  # type: ignore[arg-type]
    assert discover_sitemap("file:///etc") is None


# ── GraphQL endpoint discovery ──────────────────────────────────────────────


def test_discover_graphql_endpoints() -> None:
    urls = discover_graphql("https://example.com/shop", GRAPHQL_HTML)
    assert "https://example.com/api/graphql" in urls
    assert "https://example.com/graphql" in urls
    assert "https://example.com/v1/graphql" in urls
    assert "https://cdn.example.com/graphql-client.js" in urls


def test_discover_graphql_common_paths() -> None:
    html = '<script>const endpoint = "/api/v2/graphql";</script>'
    urls = discover_graphql("https://example.com/", html)
    assert "https://example.com/api/v2/graphql" in urls


def test_discover_graphql_empty_page() -> None:
    assert discover_graphql("https://example.com/", "<html><body>nothing</body></html>") == []
    assert discover_graphql("https://example.com/", "") == []
    assert discover_graphql("", "<html></html>") == []
    assert discover_graphql("https://example.com/", None) == []  # type: ignore[arg-type]


def test_query_graphql_posts_query() -> None:
    fake = httpx.Response(200, json={"data": {"__typename": "Query"}})
    with patch("pry.engine.scraping_methods._sync_post", return_value=fake) as mock_post:
        result = query_graphql("https://example.com/graphql", "{ __typename }", {"v": 1})
    assert result == {"data": {"__typename": "Query"}}
    assert mock_post.call_args.args == ("https://example.com/graphql",)
    assert mock_post.call_args.kwargs["json_body"] == {
        "query": "{ __typename }",
        "variables": {"v": 1},
    }


def test_query_graphql_default_variables() -> None:
    fake = httpx.Response(200, json={"data": None})
    with patch("pry.engine.scraping_methods._sync_post", return_value=fake) as mock_post:
        result = query_graphql("https://example.com/graphql", "query Q { ping }")
    assert result == {"data": None}
    assert mock_post.call_args.kwargs["json_body"]["variables"] == {}


def test_query_graphql_failures_return_none() -> None:
    with patch("pry.engine.scraping_methods._sync_post", return_value=None):
        assert query_graphql("https://example.com/graphql", "{ __typename }") is None
    fake = httpx.Response(200, text="not json")
    with patch("pry.engine.scraping_methods._sync_post", return_value=fake):
        assert query_graphql("https://example.com/graphql", "{ __typename }") is None
    fake_list = httpx.Response(200, json=[1, 2])
    with patch("pry.engine.scraping_methods._sync_post", return_value=fake_list):
        assert query_graphql("https://example.com/graphql", "{ __typename }") is None


def test_query_graphql_invalid_input_no_network() -> None:
    assert query_graphql("", "{ __typename }") is None
    assert query_graphql("https://example.com/graphql", "") is None
    assert query_graphql("https://example.com/graphql", None) is None  # type: ignore[arg-type]
    assert query_graphql("file:///etc/passwd", "{ __typename }") is None


# ── Rate-limit-aware paginated crawl ────────────────────────────────────────


def test_paginated_fetch_collects_until_empty() -> None:
    page1 = httpx.Response(200, json=[{"id": 1}, {"id": 2}])
    page2 = httpx.Response(200, json=[{"id": 3}])
    page3 = httpx.Response(200, json=[])
    with patch(
        "pry.engine.scraping_methods._sync_get", side_effect=[page1, page2, page3]
    ) as mock_get:
        results = paginated_fetch(
            "https://example.com/api/items",
            page_param="offset_page",
            max_pages=5,
            per_page_delay=0,
        )
    assert results == [{"id": 1}, {"id": 2}, {"id": 3}]
    # Stopped on the empty page 3 — never requested pages 4-5.
    assert mock_get.call_count == 3
    pages = [call.kwargs.get("params") for call in mock_get.call_args_list]
    assert pages == [{"offset_page": 1}, {"offset_page": 2}, {"offset_page": 3}]


def test_paginated_fetch_unwraps_dict_payloads() -> None:
    page1 = httpx.Response(200, json={"results": [{"id": "a"}]})
    page2 = httpx.Response(200, json={"data": [{"id": "b"}]})
    page3 = httpx.Response(200, json={"items": []})
    with patch("pry.engine.scraping_methods._sync_get", side_effect=[page1, page2, page3]):
        results = paginated_fetch("https://example.com/api/items", per_page_delay=0)
    assert results == [{"id": "a"}, {"id": "b"}]


def test_paginated_fetch_respects_max_pages() -> None:
    page = httpx.Response(200, json=[{"id": 1}])
    with patch("pry.engine.scraping_methods._sync_get", return_value=page) as mock_get:
        results = paginated_fetch("https://example.com/api/items", max_pages=2, per_page_delay=0)
    assert results == [{"id": 1}, {"id": 1}]
    assert mock_get.call_count == 2


def test_paginated_fetch_bad_json_page_stops() -> None:
    page1 = httpx.Response(200, json=[{"id": 1}])
    page2 = httpx.Response(200, text="<html>oops</html>")
    with patch("pry.engine.scraping_methods._sync_get", side_effect=[page1, page2]) as mock_get:
        results = paginated_fetch("https://example.com/api/items", per_page_delay=0)
    assert results == [{"id": 1}]
    assert mock_get.call_count == 2


def test_paginated_fetch_never_raises_on_failure() -> None:
    with patch("pry.engine.scraping_methods._sync_get", return_value=None):
        assert paginated_fetch("https://example.com/api/items", per_page_delay=0) == []


def test_paginated_fetch_invalid_input_no_network() -> None:
    assert paginated_fetch("") == []
    assert paginated_fetch(None) == []  # type: ignore[arg-type]


# ── Registry ────────────────────────────────────────────────────────────────


def test_methods_registry() -> None:
    assert set(METHODS) == {
        "feed_parsing",
        "graphql_discovery",
        "hidden_api_discovery",
        "paginated_crawl",
        "persistent_session",
        "render_wait",
        "sitemap_discovery",
    }
    for key, meta in METHODS.items():
        assert meta["name"], key
        assert meta["when"], key
        assert callable(meta["callable"]), key
    assert METHODS["hidden_api_discovery"]["callable"] is discover_json_api
    assert METHODS["persistent_session"]["callable"] is PersistentSession
    assert METHODS["render_wait"]["callable"] is fetch_rendered
    assert METHODS["feed_parsing"]["callable"] is parse_feed
    assert METHODS["feed_parsing"]["sync"] is True
    assert METHODS["sitemap_discovery"]["callable"] is parse_sitemap
    assert METHODS["sitemap_discovery"]["sync"] is True
    assert METHODS["graphql_discovery"]["callable"] is discover_graphql
    assert METHODS["graphql_discovery"]["sync"] is True
    assert METHODS["paginated_crawl"]["callable"] is paginated_fetch
    assert METHODS["paginated_crawl"]["sync"] is True
