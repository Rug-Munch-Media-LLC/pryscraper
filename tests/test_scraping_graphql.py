# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for scraping_methods — GraphQL discovery and paginated crawl."""

from __future__ import annotations

from unittest.mock import patch

import httpx

from pry.engine.scraping_methods import discover_graphql, paginated_fetch, query_graphql
from tests.support.scraping import GRAPHQL_HTML

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
    with patch("pry.engine.methods._common._sync_post", return_value=fake) as mock_post:
        result = query_graphql("https://example.com/graphql", "{ __typename }", {"v": 1})
    expected = {"data": {"__typename": "Query"}}
    assert result == expected
    expected_2 = ("https://example.com/graphql",)
    assert mock_post.call_args.args == expected_2
    expected_3 = {
        "query": "{ __typename }",
        "variables": {"v": 1},
    }
    assert mock_post.call_args.kwargs["json_body"] == expected_3


def test_query_graphql_default_variables() -> None:
    fake = httpx.Response(200, json={"data": None})
    with patch("pry.engine.methods._common._sync_post", return_value=fake) as mock_post:
        result = query_graphql("https://example.com/graphql", "query Q { ping }")
    expected = {"data": None}
    assert result == expected
    assert mock_post.call_args.kwargs["json_body"]["variables"] == {}


def test_query_graphql_failures_return_none() -> None:
    with patch("pry.engine.methods._common._sync_post", return_value=None):
        assert query_graphql("https://example.com/graphql", "{ __typename }") is None
    fake = httpx.Response(200, text="not json")
    with patch("pry.engine.methods._common._sync_post", return_value=fake):
        assert query_graphql("https://example.com/graphql", "{ __typename }") is None
    fake_list = httpx.Response(200, json=[1, 2])
    with patch("pry.engine.methods._common._sync_post", return_value=fake_list):
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
        "pry.engine.methods._common._sync_get", side_effect=[page1, page2, page3]
    ) as mock_get:
        results = paginated_fetch(
            "https://example.com/api/items",
            page_param="offset_page",
            max_pages=5,
            per_page_delay=0,
        )
    expected = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert results == expected
    # Stopped on the empty page 3 — never requested pages 4-5.
    assert mock_get.call_count == 3
    pages = [call.kwargs.get("params") for call in mock_get.call_args_list]
    expected_2 = [{"offset_page": 1}, {"offset_page": 2}, {"offset_page": 3}]
    assert pages == expected_2
