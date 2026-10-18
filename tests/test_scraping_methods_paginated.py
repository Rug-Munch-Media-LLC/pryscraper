"""Tests for scraping_methods — hidden-API discovery, session persistence,
render-wait, feed parsing, sitemap discovery, GraphQL, paginated crawl.

All tests are offline: httpx traffic uses ``httpx.MockTransport`` (or a
patched ``_sync_get`` / ``_sync_post``) and browser tiers use fake Playwright
/ Camoufox objects. No live network or browser.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx

from pry.engine.scraping_methods import (
    paginated_fetch,
)

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


def test_paginated_fetch_unwraps_dict_payloads() -> None:
    page1 = httpx.Response(200, json={"results": [{"id": "a"}]})
    page2 = httpx.Response(200, json={"data": [{"id": "b"}]})
    page3 = httpx.Response(200, json={"items": []})
    with patch("pry.engine.methods._common._sync_get", side_effect=[page1, page2, page3]):
        results = paginated_fetch("https://example.com/api/items", per_page_delay=0)
    expected = [{"id": "a"}, {"id": "b"}]
    assert results == expected


def test_paginated_fetch_respects_max_pages() -> None:
    page = httpx.Response(200, json=[{"id": 1}])
    with patch("pry.engine.methods._common._sync_get", return_value=page) as mock_get:
        results = paginated_fetch("https://example.com/api/items", max_pages=2, per_page_delay=0)
    expected = [{"id": 1}, {"id": 1}]
    assert results == expected
    assert mock_get.call_count == 2


def test_paginated_fetch_bad_json_page_stops() -> None:
    page1 = httpx.Response(200, json=[{"id": 1}])
    page2 = httpx.Response(200, text="<html>oops</html>")
    with patch("pry.engine.methods._common._sync_get", side_effect=[page1, page2]) as mock_get:
        results = paginated_fetch("https://example.com/api/items", per_page_delay=0)
    expected = [{"id": 1}]
    assert results == expected
    assert mock_get.call_count == 2


def test_paginated_fetch_never_raises_on_failure() -> None:
    with patch("pry.engine.methods._common._sync_get", return_value=None):
        assert paginated_fetch("https://example.com/api/items", per_page_delay=0) == []


def test_paginated_fetch_invalid_input_no_network() -> None:
    assert paginated_fetch("") == []
    assert paginated_fetch(None) == []  # type: ignore[arg-type]
