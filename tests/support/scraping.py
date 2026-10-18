# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared offline fixtures/fakes for the scraping-methods test modules.

No live network or browser: httpx traffic uses ``httpx.MockTransport`` (or a
patched ``_sync_get`` / ``_sync_post``) and browser tiers use fake Playwright /
Camoufox objects.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx

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

    def route(self, *args: Any, **kwargs: Any) -> None:
        """Record the SSRF route-guard registration (sync in Playwright)."""
        self.routes = [*getattr(self, "routes", []), args]

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


def fake_playwright(
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


def ok_handler() -> Any:
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
