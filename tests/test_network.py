# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for network capture utilities."""

from pry.engine.network import (
    extract_api_calls_from_html,
    extract_graphql_queries,
    extract_json_ld,
    extract_nextjs_props,
    extract_nuxt_state,
)


def test_extract_fetch_calls() -> None:
    html = """<script>fetch('/api/users'); fetch("https://api.example.com/data")</script>"""
    calls = extract_api_calls_from_html(html)
    assert len(calls) >= 2
    urls = [c["url"] for c in calls]
    assert "/api/users" in urls
    assert "https://api.example.com/data" in urls


def test_extract_axios_calls() -> None:
    html = """<script>axios.get('/api/products'); axios.post('/api/orders')</script>"""
    calls = extract_api_calls_from_html(html)
    assert len(calls) >= 2


def test_extract_json_ld() -> None:
    html = """<script type="application/ld+json">{"@type":"WebSite","name":"Test"}</script>"""
    data = extract_json_ld(html)
    assert len(data) == 1
    assert data[0]["name"] == "Test"


def test_extract_graphql() -> None:
    html = """<script>const q = gql`{ users { id name } }`</script>"""
    queries = extract_graphql_queries(html)
    assert len(queries) >= 1
    assert "users" in queries[0]["query"]


def test_nextjs_props() -> None:
    html = """<script>window.__NEXT_DATA__ = {"props":{"pageProps":{"title":"Hello"}}}</script>"""
    data = extract_nextjs_props(html)
    assert data is not None
    assert data["props"]["pageProps"]["title"] == "Hello"


def test_nuxt_state() -> None:
    html = """<script>window.__NUXT__ = {"data":[{"key":"value"}]}</script>"""
    data = extract_nuxt_state(html)
    assert data is not None
