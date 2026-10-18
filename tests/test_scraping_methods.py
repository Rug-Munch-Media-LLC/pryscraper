# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for scraping_methods — hidden-API discovery and the method registry."""

from __future__ import annotations

import pytest

from pry.engine.scraping_methods import (
    METHODS,
    PersistentSession,
    discover_graphql,
    discover_json_api,
    fetch_rendered,
    paginated_fetch,
    parse_feed,
    parse_sitemap,
)
from tests.support.scraping import FIXTURE_HTML

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


# ── Registry ────────────────────────────────────────────────────────────────


def test_methods_registry() -> None:
    expected = {
        "feed_parsing",
        "graphql_discovery",
        "hidden_api_discovery",
        "paginated_crawl",
        "persistent_session",
        "render_wait",
        "sitemap_discovery",
    }
    assert set(METHODS) == expected
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
