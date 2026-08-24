# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for advanced scraping features (TLS fingerprinting, GraphQL, Schema.org, WebSocket)."""

from pry.engine.graphql_discovery import GraphQLDiscovery
from pry.engine.schema_extraction import SchemaExtractor
from pry.engine.tls_fingerprint import BROWSER_FINGERPRINTS, TLSScraper
from pry.engine.websocket_scraper import WebSocketScraper


def test_tls_browser_fingerprints() -> None:
    assert len(BROWSER_FINGERPRINTS) >= 10
    assert "chrome" in BROWSER_FINGERPRINTS
    assert "firefox" in BROWSER_FINGERPRINTS
    assert "safari" in BROWSER_FINGERPRINTS


def test_tls_scraper_init() -> None:
    s = TLSScraper()
    assert s.default_impersonate in BROWSER_FINGERPRINTS
    assert hasattr(s, "fetch")
    assert hasattr(s, "fetch_with_rotation")


def test_tls_scraper_invalid_fingerprint_fallback() -> None:
    s = TLSScraper(default_impersonate="not_a_real_browser")
    assert s.default_impersonate == "chrome"


def test_tls_scraper_is_available() -> None:
    s = TLSScraper()
    assert isinstance(s.is_available(), bool)


def test_graphql_common_paths() -> None:
    g = GraphQLDiscovery()
    assert "/graphql" in g.COMMON_PATHS
    assert "/api/graphql" in g.COMMON_PATHS
    assert len(g.COMMON_PATHS) >= 10
    assert "graphql" in g.INTROSPECTION_QUERY


def test_graphql_introspection_query() -> None:
    g = GraphQLDiscovery()
    assert "__schema" in g.INTROSPECTION_QUERY
    assert "queryType" in g.INTROSPECTION_QUERY
    assert "fields" in g.INTROSPECTION_QUERY


def test_graphql_extract_endpoints_from_js() -> None:
    g = GraphQLDiscovery()
    js = """
    const endpoint = "/graphql/v1";
    const alt = "https://api.example.com/graphql";
    const link = createHttpLink({ uri: "/api/graphql" });
    const apollo = apolloClient.link("https://x.com/graphql");
    """
    endpoints = g.extract_endpoints_from_js(js)
    assert len(endpoints) >= 3
    assert any("/graphql" in e for e in endpoints)


def test_graphql_endpoint_patterns() -> None:
    g = GraphQLDiscovery()
    assert len(g.ENDPOINT_PATTERNS) >= 5
    for pattern in g.ENDPOINT_PATTERNS:
        import re as _re

        assert _re.compile(pattern), f"Invalid regex: {pattern}"


def test_schema_extractor_jsonld() -> None:
    e = SchemaExtractor()
    html = '<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Test","price":99}</script></html>'
    result = e.extract_jsonld(html)
    assert len(result) == 1
    assert result[0]["@type"] == "Product"
    assert result[0]["name"] == "Test"


def test_schema_extractor_jsonld_with_graph() -> None:
    e = SchemaExtractor()
    html = '<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Article","headline":"A"},{"@type":"Person","name":"B"}]}</script></html>'
    result = e.extract_jsonld(html)
    assert len(result) == 2
    assert result[0]["@type"] == "Article"
    assert result[1]["@type"] == "Person"


def test_schema_extractor_jsonld_array() -> None:
    e = SchemaExtractor()
    html = '<html><script type="application/ld+json">[{"@type":"Product","name":"A"},{"@type":"Product","name":"B"}]</script></html>'
    result = e.extract_jsonld(html)
    assert len(result) == 2


def test_schema_extractor_jsonld_invalid() -> None:
    e = SchemaExtractor()
    html = '<html><script type="application/ld+json">not valid json {{{</script></html>'
    result = e.extract_jsonld(html)
    assert result == []


def test_schema_extractor_all() -> None:
    e = SchemaExtractor()
    html = (
        "<html><body>"
        '<script type="application/ld+json">{"@type":"Article","headline":"Test"}</script>'
        '<div itemscope itemtype="https://schema.org/Product">'
        '<span itemprop="name">Widget</span>'
        "</div>"
        "</body></html>"
    )
    result = e.extract_all(html)
    assert result["count"] >= 2
    types = [item["type"] for item in result["normalized"]]
    assert "Article" in types or "Product" in types


def test_schema_types() -> None:
    e = SchemaExtractor()
    assert "Product" in e.SCHEMA_TYPES
    assert "Article" in e.SCHEMA_TYPES
    assert "Event" in e.SCHEMA_TYPES


def test_schema_normalize() -> None:
    e = SchemaExtractor()
    item = {"@context": "https://schema.org", "@type": "Product", "name": "X"}
    norm = e._normalize(item)
    assert norm["type"] == "Product"
    assert norm["source"] == "jsonld"
    assert norm["data"]["name"] == "X"


def test_websocket_scraper_init() -> None:
    s = WebSocketScraper()
    assert s.max_messages == 100
    assert s.timeout == 30
    assert hasattr(s, "scrape_websocket")
    assert hasattr(s, "scrape_sse")


def test_websocket_scraper_custom_params() -> None:
    s = WebSocketScraper(max_messages=50, timeout=15)
    assert s.max_messages == 50
    assert s.timeout == 15
