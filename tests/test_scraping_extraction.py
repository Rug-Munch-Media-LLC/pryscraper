# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for scraping_methods — feed parsing and sitemap discovery."""

from __future__ import annotations

from unittest.mock import patch

import httpx

from pry.engine.scraping_methods import (
    discover_feed,
    discover_sitemap,
    parse_feed,
    parse_sitemap,
)
from tests.support.scraping import (
    ATOM_FIXTURE,
    FEED_LINK_HTML,
    ROBOTS_TXT,
    RSS_FIXTURE,
    SITEMAP_INDEX_FIXTURE,
    SITEMAP_PAGES_FIXTURE,
    SITEMAP_URLSET_FIXTURE,
)


def test_parse_rss_feed() -> None:
    fake = httpx.Response(200, text=RSS_FIXTURE)
    with patch("pry.engine.methods._common._sync_get", return_value=fake):
        entries = parse_feed("https://example.com/feed.xml")
    assert len(entries) == 3
    expected = {
        "title": "First post",
        "link": "https://example.com/posts/1",
        "summary": "Summary one",
        "published": "Mon, 17 Aug 2026 10:00:00 GMT",
    }
    assert entries[0] == expected
    assert entries[1]["title"] == "Second post"
    # Fields absent from an item stay empty strings.
    expected_2 = {
        "title": "No extras",
        "link": "https://example.com/posts/3",
        "summary": "",
        "published": "",
    }
    assert entries[2] == expected_2


def test_parse_atom_feed() -> None:
    fake = httpx.Response(200, text=ATOM_FIXTURE)
    with patch("pry.engine.methods._common._sync_get", return_value=fake):
        entries = parse_feed("https://example.com/atom.xml")
    assert len(entries) == 2
    expected = {
        "title": "Atom entry one",
        "link": "https://example.com/entries/1",
        "summary": "Atom summary one",
        "published": "2026-08-17T10:00:00Z",
    }
    assert entries[0] == expected
    # <content> falls back to summary; <updated> falls back to published.
    assert entries[1]["summary"] == "<p>Content two</p>"
    assert entries[1]["published"] == "2026-08-18T11:30:00Z"


def test_parse_feed_non_feed_xml_returns_empty() -> None:
    fake = httpx.Response(200, text="<html><body>not a feed</body></html>")
    with patch("pry.engine.methods._common._sync_get", return_value=fake):
        assert parse_feed("https://example.com/feed.xml") == []


def test_parse_feed_malformed_xml_returns_empty() -> None:
    fake = httpx.Response(200, text="<rss><channel>unclosed")
    with patch("pry.engine.methods._common._sync_get", return_value=fake):
        assert parse_feed("https://example.com/feed.xml") == []


def test_parse_feed_fetch_failure_returns_empty() -> None:
    with patch("pry.engine.methods._common._sync_get", return_value=None):
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


def test_parse_sitemap_urlset() -> None:
    fake = httpx.Response(200, text=SITEMAP_URLSET_FIXTURE)
    with patch("pry.engine.methods._common._sync_get", return_value=fake) as mock_get:
        urls = parse_sitemap("https://example.com/sitemap.xml")
    expected = [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/posts/1",
    ]
    assert urls == expected
    assert mock_get.call_count == 1


def test_parse_sitemap_index_recurses() -> None:
    index = httpx.Response(200, text=SITEMAP_INDEX_FIXTURE)
    posts = httpx.Response(200, text=SITEMAP_URLSET_FIXTURE)
    pages = httpx.Response(200, text=SITEMAP_PAGES_FIXTURE)
    with patch(
        "pry.engine.methods._common._sync_get", side_effect=[index, posts, pages]
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
    with patch("pry.engine.methods._common._sync_get", return_value=self_index) as mock_get:
        urls = parse_sitemap("https://example.com/sitemap.xml")
    assert urls == []
    assert mock_get.call_count == 1


def test_parse_sitemap_bad_xml_returns_empty() -> None:
    fake = httpx.Response(200, text="not xml at all")
    with patch("pry.engine.methods._common._sync_get", return_value=fake):
        assert parse_sitemap("https://example.com/sitemap.xml") == []


def test_parse_sitemap_fetch_failure_returns_empty() -> None:
    with patch("pry.engine.methods._common._sync_get", return_value=None):
        assert parse_sitemap("https://example.com/sitemap.xml") == []


def test_parse_sitemap_invalid_input_no_network() -> None:
    assert parse_sitemap("") == []
    assert parse_sitemap(None) == []  # type: ignore[arg-type]


def test_discover_sitemap_via_robots() -> None:
    fake = httpx.Response(200, text=ROBOTS_TXT)
    with patch("pry.engine.methods._common._sync_get", return_value=fake) as mock_get:
        found = discover_sitemap("https://example.com")
    assert found == "https://example.com/sitemap.xml"
    assert mock_get.call_count == 1
    expected = ("https://example.com/robots.txt",)
    assert mock_get.call_args.args == expected


def test_discover_sitemap_robots_without_sitemap_line_falls_back() -> None:
    fake = httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
    with patch("pry.engine.methods._common._sync_get", return_value=fake):
        assert discover_sitemap("example.com") == "https://example.com/sitemap.xml"


def test_discover_sitemap_robots_unreachable_falls_back() -> None:
    with patch("pry.engine.methods._common._sync_get", return_value=None):
        assert discover_sitemap("https://example.com") == "https://example.com/sitemap.xml"


def test_discover_sitemap_invalid_domain() -> None:
    assert discover_sitemap("") is None
    assert discover_sitemap(None) is None  # type: ignore[arg-type]
    assert discover_sitemap("file:///etc") is None
