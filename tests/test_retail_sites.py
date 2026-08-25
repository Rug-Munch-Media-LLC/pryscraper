# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for marketplace.retail (Target / Best Buy / Costco / Home Depot / Lowe's / Macy's / Kohl's / Staples).

Covers JSON-LD ``Product`` / ``ItemList`` extraction, the embedded
``__NEXT_DATA__`` / ``__INITIAL_STATE__`` fallback, the OpenGraph last
resort, the never-raise contract (HTTP 500s, transport errors, empty
queries, unknown stores all degrade to ``[]`` / ``{}``), the
``store="all"`` aggregation with per-store degradation, and the
``commerce_data`` integration (``search_product`` / ``get_product`` with
``marketplace="target" | "bestbuy"``).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

import datasets.commerce_data as commerce_data
import datasets.commerce_data.marketplaces as marketplaces
import pry.commerce.marketplace.retail as retail

RETAIL_SCHEMA_KEYS = {
    "store",
    "product_id",
    "title",
    "price",
    "currency",
    "seller",
    "rating",
    "stock",
    "url",
    "confidence",
}
COMMERCE_SCHEMA_KEYS = {
    "id",
    "title",
    "price",
    "currency",
    "seller",
    "rating",
    "url",
    "marketplace",
}


@pytest.fixture(autouse=True)
def _hermetic_retail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retail tests hermetic: no retries, no backoff sleeps, no proxy pool."""
    monkeypatch.setenv("PRY_MARKETPLACE_HTTP_RETRIES", "1")
    monkeypatch.setenv("PRY_SECRET_BACKEND", "env")
    monkeypatch.delenv("WEBSHARE_PROXY_LIST", raising=False)
    monkeypatch.setattr(retail, "RETRY_BASE", 0.0)
    monkeypatch.setattr(retail, "MAX_BACKOFF", 0.0)
    monkeypatch.setattr(retail, "_next_proxy", lambda: None)


# ── Fixture HTML builders ──────────────────────────────────────────────


def _target_product_html() -> str:
    return """<html><head>
<script type="application/ld+json">{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
  "sku": "A-80770713",
  "brand": {"@type": "Brand", "name": "Sony"},
  "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.7"},
  "offers": {"@type": "Offer", "price": "399.99", "priceCurrency": "USD",
             "availability": "https://schema.org/InStock"}
}</script></head><body></body></html>"""


def _target_search_html() -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "item": {
                    "@type": "Product",
                    "name": "Target 55-Inch 4K TV",
                    "sku": "A-1001",
                    "offers": {"@type": "Offer", "price": "299.99", "priceCurrency": "USD"},
                },
            },
            {
                "@type": "ListItem",
                "position": 2,
                "item": {
                    "@type": "Product",
                    "name": "Target 65-Inch 4K TV",
                    "sku": "A-1002",
                    "offers": {"@type": "Offer", "price": "499.99", "priceCurrency": "USD"},
                },
            },
        ],
    }
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(data)
        + "</script></head><body></body></html>"
    )


def _bestbuy_product_state() -> dict[str, Any]:
    return {
        "props": {
            "pageProps": {
                "product": {
                    "sku": "6455735",
                    "name": "Apple MacBook Air 13",
                    "price": 1099.99,
                    "customerReviewAverage": 4.8,
                    "availability": "InStock",
                    "seller": "Best Buy",
                    "url": "/site/apple-macbook-air-13/6455735.p",
                }
            }
        }
    }


def _bestbuy_product_html() -> str:
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(_bestbuy_product_state())
        + "</script></head><body></body></html>"
    )


def _bestbuy_search_html() -> str:
    state = {
        "props": {
            "pageProps": {
                "searchResults": [
                    {
                        "sku": "6455735",
                        "name": "MacBook Air 13",
                        "price": 999.99,
                        "customerReviewAverage": 4.6,
                    },
                    {
                        "sku": "6455736",
                        "name": "MacBook Pro 14",
                        "price": 1999.99,
                        "customerReviewAverage": 4.9,
                    },
                ]
            }
        }
    }
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(state)
        + "</script></head><body></body></html>"
    )


def _lowes_product_html() -> str:
    return (
        "<html><body><script>window.__INITIAL_STATE__ = "
        + json.dumps(
            {
                "product": {
                    "productId": "50123456",
                    "productName": "Kobalt 24V Max Brushless Drill",
                    "price": {"amount": 12900, "divisor": 100},
                    "brandName": "Kobalt",
                    "rating": 4.5,
                }
            }
        )
        + ";</script></body></html>"
    )


def _costco_product_html() -> str:
    return """<html><head>
<script type="application/ld+json">{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Kirkland Signature Paper Towels",
  "sku": "Item-100891234",
  "offers": [
    {"@type": "Offer", "price": "24.99", "priceCurrency": "USD",
     "availability": "https://schema.org/OutOfStock"},
    {"@type": "Offer", "price": "29.99", "priceCurrency": "USD"}
  ]
}</script></head><body></body></html>"""


def _kohls_og_html() -> str:
    return """<html><head>
<meta property="og:title" content="Kohl's Flannel Shirt">
<meta property="og:price:amount" content="34.50">
<meta property="og:price:currency" content="USD">
<meta property="og:url" content="https://www.kohls.com/product/prd-5834471/kohls-flannel-shirt">
</head><body></body></html>"""


def _mock_all_search_routes_fallback() -> None:
    """Register 404 routes for every store's search URL (used by store="all" tests)."""
    for info in retail._STORES.values():
        prefix = info["search_url"].split("?")[0]
        respx.get(url__startswith=prefix).mock(return_value=httpx.Response(404))


# ── Package surface / registry ─────────────────────────────────────────


def test_retail_module_surface() -> None:
    assert callable(retail.search_retail)
    assert callable(retail.get_retail_product)
    assert set(retail.__all__) == {"search_retail", "get_retail_product"}


def test_store_registry_shape() -> None:
    assert len(retail._STORES) == 8
    expected = {"target", "bestbuy", "costco", "homedepot", "lowes", "macys", "kohls", "staples"}
    assert set(retail._STORES) == expected
    for _key, info in retail._STORES.items():
        assert info["confidence"] in ("high", "medium", "low")
        assert "{q}" in info["search_url"]
        assert "{product_id}" in info["product_url"]
        assert info["host"]
        assert isinstance(info["js_gated"], bool)


def test_store_aliases() -> None:
    assert retail._normalize_store("target") == "target"
    assert retail._normalize_store("TARGET") == "target"
    assert retail._normalize_store("best buy") == "bestbuy"
    assert retail._normalize_store("home depot") == "homedepot"
    assert retail._normalize_store("Lowe's") == "lowes"
    assert retail._normalize_store("Macy's") == "macys"
    assert retail._normalize_store("Kohl's") == "kohls"
    assert retail._normalize_store("nordstrom") == ""
    assert retail._normalize_store("") == ""


def test_commerce_package_surface() -> None:
    assert "target" in marketplaces.MARKETPLACES
    assert "bestbuy" in marketplaces.MARKETPLACES
    assert hasattr(commerce_data, "search_product")
    assert hasattr(commerce_data, "get_product")


# ── get_retail_product: JSON-LD Product ────────────────────────────────


async def test_target_get_product_json_ld() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.target.com/p/").mock(
            return_value=httpx.Response(200, text=_target_product_html())
        )
        result = await retail.get_retail_product("target", "A-80770713")
    assert set(result) == RETAIL_SCHEMA_KEYS
    assert result["store"] == "target"
    assert result["product_id"] == "A-80770713"
    assert result["title"] == "Sony WH-1000XM5 Wireless Noise Canceling Headphones"
    assert result["price"] == 399.99
    assert result["currency"] == "USD"
    assert result["seller"] == "Sony"
    assert result["rating"] == 4.7
    assert result["stock"] is True
    assert result["url"] == "https://www.target.com/p/A-80770713"
    assert result["confidence"] == "medium"


async def test_costco_get_product_json_ld_offer_list() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.costco.com/").mock(
            return_value=httpx.Response(200, text=_costco_product_html())
        )
        result = await retail.get_retail_product("costco", "Item-100891234")
    assert result["product_id"] == "Item-100891234"
    assert result["title"] == "Kirkland Signature Paper Towels"
    assert result["price"] == 24.99  # first offer wins
    assert result["currency"] == "USD"
    assert result["stock"] is False  # OutOfStock on the first offer
    assert result["url"] == "https://www.costco.com/Item-100891234.html"


# ── get_retail_product: embedded state fallback ────────────────────────


async def test_bestbuy_get_product_next_data() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.bestbuy.com/site/").mock(
            return_value=httpx.Response(200, text=_bestbuy_product_html())
        )
        result = await retail.get_retail_product("bestbuy", "6455735")
    assert set(result) == RETAIL_SCHEMA_KEYS
    assert result["store"] == "bestbuy"
    assert result["product_id"] == "6455735"
    assert result["title"] == "Apple MacBook Air 13"
    assert result["price"] == 1099.99
    assert result["currency"] is None
    assert result["seller"] == "Best Buy"
    assert result["rating"] == 4.8
    assert result["stock"] is True
    assert result["url"] == "https://www.bestbuy.com/site/apple-macbook-air-13/6455735.p"


async def test_lowes_get_product_initial_state() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.lowes.com/pd/").mock(
            return_value=httpx.Response(200, text=_lowes_product_html())
        )
        result = await retail.get_retail_product("lowe's", "50123456")
    assert result["product_id"] == "50123456"
    assert result["title"] == "Kobalt 24V Max Brushless Drill"
    assert result["price"] == 129.0  # 12900 cents / 100
    assert result["seller"] == "Kobalt"
    assert result["rating"] == 4.5
    assert result["url"] == "https://www.lowes.com/pd/50123456"


# ── get_retail_product: OG meta last resort ────────────────────────────


async def test_kohls_get_product_og_fallback() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.kohls.com/product/").mock(
            return_value=httpx.Response(200, text=_kohls_og_html())
        )
        result = await retail.get_retail_product("kohl's", "5834471")
    assert result["store"] == "kohls"
    assert result["product_id"] == "5834471"
    assert result["title"] == "Kohl's Flannel Shirt"
    assert result["price"] == 34.5
    assert result["currency"] == "USD"
    assert result["confidence"] == "low"


# ── search_retail ──────────────────────────────────────────────────────


async def test_target_search_json_ld_item_list() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.target.com/s").mock(
            return_value=httpx.Response(200, text=_target_search_html())
        )
        results = await retail.search_retail("tv", store="target", limit=1)
    assert len(results) == 1  # limit honored
    first = results[0]
    assert set(first) == RETAIL_SCHEMA_KEYS
    assert first["product_id"] == "A-1001"
    assert first["title"] == "Target 55-Inch 4K TV"
    assert first["price"] == 299.99
    assert first["currency"] == "USD"
    assert first["url"] == "https://www.target.com/p/A-1001"


async def test_bestbuy_search_next_data_deep_walk() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.bestbuy.com/site/searchpage.jsp").mock(
            return_value=httpx.Response(200, text=_bestbuy_search_html())
        )
        results = await retail.search_retail("macbook", store="bestbuy", limit=5)
    assert len(results) == 2
    assert [r["product_id"] for r in results] == ["6455735", "6455736"]
    assert results[0]["price"] == 999.99
    assert results[0]["url"] == "https://www.bestbuy.com/site/6455735"


async def test_search_all_stores_aggregates_with_degradation() -> None:
    async with respx.mock:
        _mock_all_search_routes_fallback()
        respx.get(url__startswith="https://www.target.com/s").mock(
            return_value=httpx.Response(200, text=_target_search_html())
        )
        respx.get(url__startswith="https://www.bestbuy.com/site/searchpage.jsp").mock(
            return_value=httpx.Response(200, text=_bestbuy_search_html())
        )
        results = await retail.search_retail("tv", store="all", limit=20)
    stores = {r["store"] for r in results}
    assert "target" in stores
    assert "bestbuy" in stores
    assert len(results) == 4  # 2 target + 2 bestbuy; other stores degraded to []


async def test_search_unknown_store_returns_empty() -> None:
    assert await retail.search_retail("tv", store="nordstrom") == []


async def test_search_empty_query_returns_empty() -> None:
    assert await retail.search_retail("") == []
    assert await retail.search_retail("   ") == []


# ── never-raise contract ───────────────────────────────────────────────


async def test_get_product_http_500_returns_empty() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.target.com/p/").mock(
            return_value=httpx.Response(500, text="boom")
        )
        assert await retail.get_retail_product("target", "A-123") == {}


async def test_get_product_transport_error_returns_empty() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.target.com/p/").mock(
            side_effect=httpx.ConnectError("boom")
        )
        assert await retail.get_retail_product("target", "A-123") == {}


async def test_get_product_garbage_page_returns_empty() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.target.com/p/").mock(
            return_value=httpx.Response(200, text="<html>nothing here</html>")
        )
        assert await retail.get_retail_product("target", "A-123") == {}


async def test_get_product_empty_id_returns_empty() -> None:
    assert await retail.get_retail_product("target", "") == {}


async def test_get_product_unknown_store_returns_empty() -> None:
    assert await retail.get_retail_product("nordstrom", "1") == {}


async def test_search_store_down_returns_empty() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.target.com/s").mock(
            return_value=httpx.Response(500, text="boom")
        )
        assert await retail.search_retail("tv", store="target") == []


async def test_search_transport_error_returns_empty() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.target.com/s").mock(
            side_effect=httpx.ConnectError("boom")
        )
        assert await retail.search_retail("tv", store="target") == []


# ── commerce_data integration ──────────────────────────────────────────


async def test_commerce_search_target_routes_through_retail() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.target.com/s").mock(
            return_value=httpx.Response(200, text=_target_search_html())
        )
        results = await marketplaces.search_product("tv", marketplace="target")
    assert len(results) == 2
    first = results[0]
    assert set(first) == COMMERCE_SCHEMA_KEYS
    assert first["marketplace"] == "target"
    assert first["id"] == "A-1001"
    assert first["title"] == "Target 55-Inch 4K TV"
    assert first["price"] == 299.99


async def test_commerce_get_bestbuy_routes_through_retail() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.bestbuy.com/site/").mock(
            return_value=httpx.Response(200, text=_bestbuy_product_html())
        )
        product = await marketplaces.get_product("6455735", marketplace="bestbuy")
    assert set(product) == COMMERCE_SCHEMA_KEYS
    assert product["marketplace"] == "bestbuy"
    assert product["id"] == "6455735"
    assert product["title"] == "Apple MacBook Air 13"
    assert product["price"] == 1099.99
    assert product["rating"] == 4.8


async def test_commerce_retail_http_error_returns_empty() -> None:
    async with respx.mock:
        respx.get(url__startswith="https://www.target.com/s").mock(
            return_value=httpx.Response(403, text="forbidden")
        )
        assert await marketplaces.search_product("tv", marketplace="target") == []


async def test_commerce_unknown_marketplace_still_empty() -> None:
    assert await marketplaces.search_product("x", marketplace="walmart") == []
    assert await marketplaces.get_product("1", marketplace="walmart") == {}
