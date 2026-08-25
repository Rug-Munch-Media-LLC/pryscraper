# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for marketplace (Amazon/Walmart/TikTok Shop scrapers), x402 middleware, and webhooks.

The marketplace scraper section mocks every HTTP response with respx — no
live network. It covers normalization into the shared schema, empty-on-
failure, anti-bot/robots handling, and the never-raise contract.
"""

import asyncio
import json
from typing import Any

import httpx
import pytest
import respx

import marketplace as _marketplace_pkg
import pry.api.client as _client_module
from marketplace import amazon, tiktok_shop, walmart
from pry.api.webhook_delivery import WebhookDelivery
from pry.commerce.actor_marketplace import Actor, ActorMarketplace, ActorVisibility
from pry.payments.x402_middleware import PAID_ENDPOINTS, X402_PRICING


def test_x402_pricing() -> None:
    assert "scrape" in X402_PRICING
    assert X402_PRICING["scrape"]["price_usd"] > 0
    for info in X402_PRICING.values():
        assert "price_usd" in info
        assert "description" in info


def test_x402_paid_endpoints() -> None:
    assert "/v1/scrape" in PAID_ENDPOINTS
    assert "/v1/crawl" in PAID_ENDPOINTS
    assert len(PAID_ENDPOINTS) >= 5


def test_x402_middleware_signing() -> None:
    w = WebhookDelivery(signing_secret="test-secret")
    sig = w.sign_payload({"event": "test", "data": {"x": 1}})
    assert isinstance(sig, str)
    assert len(sig) == 64  # SHA-256 hex


def test_actor_marketplace_create() -> None:
    m = ActorMarketplace()
    actor = m.create(
        "Test Actor",
        "Test description",
        template_id="amazon-product",
        price_per_run=0.01,
        visibility=ActorVisibility.PRIVATE,
        tags=["e-commerce"],
    )
    assert actor.name == "Test Actor"
    assert actor.template_id == "amazon-product"
    assert actor.price_per_run == 0.01
    assert "e-commerce" in actor.tags


def test_actor_marketplace_list() -> None:
    m = ActorMarketplace()
    m.create("Test 1", "Desc", tags=["test"])
    actors = m.list()
    assert len(actors) >= 1


def test_actor_marketplace_filter() -> None:
    m = ActorMarketplace()
    m.create("Public", "D", visibility=ActorVisibility.PUBLIC, tags=["free"])
    m.create("Private", "D", visibility=ActorVisibility.PRIVATE, tags=["private"])
    public = m.list(visibility="public")
    private = m.list(visibility="private")
    assert all(a["visibility"] == "public" for a in public)
    assert all(a["visibility"] == "private" for a in private)


def test_actor_marketplace_run_missing() -> None:
    m = ActorMarketplace()
    result = asyncio.run(m.run("nonexistent"))
    assert result["success"] is False


def test_actor_to_dict() -> None:
    a = Actor("id1", "Name", "Desc")
    d = a.to_dict()
    assert d["name"] == "Name"
    assert d["actor_id"] == "id1"
    assert "created_at" in d


def test_webhook_signature_consistency() -> None:
    w1 = WebhookDelivery(signing_secret="same-secret")
    w2 = WebhookDelivery(signing_secret="same-secret")
    payload = {"event": "test", "x": 1}
    assert w1.sign_payload(payload) == w2.sign_payload(payload)


def test_webhook_different_secrets() -> None:
    w1 = WebhookDelivery(signing_secret="secret1")
    w2 = WebhookDelivery(signing_secret="secret2")
    payload = {"event": "test"}
    assert w1.sign_payload(payload) != w2.sign_payload(payload)


def test_actor_visibility_enum() -> None:
    assert ActorVisibility.PRIVATE.value == "private"
    assert ActorVisibility.PUBLIC.value == "public"
    assert ActorVisibility.UNLISTED.value == "unlist"


# ══════════════════════════════════════════════════════════════════════
# marketplace scraper package — Amazon / Walmart / TikTok Shop
# All HTTP is mocked with respx; no live network.
# ══════════════════════════════════════════════════════════════════════

AMAZON_PRODUCT_URL = "https://www.amazon.com/dp/B0TEST1234"
AMAZON_SEARCH_URL = "https://www.amazon.com/s"
AMAZON_ROBOTS_URL = "https://www.amazon.com/robots.txt"
WALMART_PRODUCT_URL = "https://www.walmart.com/ip/12345678"
WALMART_SEARCH_URL = "https://www.walmart.com/search"
TIKTOK_RENDER_URL = "https://www.tiktok.com/shop/pdp/render/9988776655"
TIKTOK_PDP_URL = "https://www.tiktok.com/shop/pdp/9988776655"
TIKTOK_TRENDING_URL = "https://www.tiktok.com/shop/v2/best_sellers"

AMAZON_SCHEMA_KEYS = {
    "asin",
    "title",
    "price",
    "currency",
    "buy_box",
    "brand",
    "rating",
    "review_count",
    "bsr",
    "category",
    "offers",
    "url",
}
WALMART_SCHEMA_KEYS = {
    "product_id",
    "title",
    "price",
    "currency",
    "seller",
    "rating",
    "stock",
    "url",
}
TIKTOK_SCHEMA_KEYS = {
    "product_id",
    "title",
    "price",
    "sold_count",
    "gmv_estimate",
    "rating",
    "shop",
    "url",
}


@pytest.fixture(autouse=True)
def _hermetic_marketplace(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Make marketplace tests hermetic: no robots fetch, no retries, no caches."""
    monkeypatch.setenv("PRY_MARKETPLACE_HONOR_ROBOTS", "0")
    monkeypatch.setenv("PRY_MARKETPLACE_HTTP_RETRIES", "1")
    monkeypatch.delenv("PRY_MARKETPLACE_USER_AGENT", raising=False)
    monkeypatch.delenv("RAINFOREST_API_KEY", raising=False)
    monkeypatch.delenv("PRY_RAINFOREST_API_KEY", raising=False)
    monkeypatch.delenv("PRY_TIKTOK_TRENDING_PLACEHOLDER", raising=False)
    _client_module.http_client = None
    tiktok_shop._reset_gmv_snapshots()
    from marketplace import _clear_robots_cache

    _clear_robots_cache()
    yield
    # Never leak a respx-bound client into later tests.
    _client_module.http_client = None


# ── Fixture HTML / JSON builders ───────────────────────────────────────


def _amazon_product_html() -> str:
    return """<html><body>
    <span id="productTitle">Apple iPhone 15 Pro 128GB</span>
    <span class="a-price a-text-price"><span class="a-offscreen">$1,099.00</span></span>
    <div id="corePrice_feature_div"><span class="priceToPay"><span class="a-price"><span class="a-offscreen">$999.99</span></span></span></div>
    <span id="sellerProfileTriggerId">Apple</span>
    <a id="bylineInfo">Visit the Apple Store</a>
    <span id="acrPopover"><span class="a-icon-alt">4.8 out of 5 stars</span></span>
    <span id="acrCustomerReviewText">12,345 ratings</span>
    <span class="a-badge-text">Amazon's Choice</span>
    <table id="productDetails_detailBullets_sections1"><tr><th>Best Sellers Rank</th><td><span>#87 in Cell Phones &amp; Accessories (See Top 100 in Cell Phones &amp; Accessories)</span></td></tr></table>
    <div id="olp-upd-new-used"><span>New (14) from $949.99</span></div>
    </body></html>"""


def _amazon_search_html(items: list[dict[str, Any]]) -> str:
    blocks = []
    for item in items:
        blocks.append(
            f"""<div data-component-type="s-search-result" data-asin="{item["asin"]}">
        <div class="sg-col-inner">
          <h2><a class="a-link-normal" href="/dp/{item["asin"]}?th=1"><span>{item["title"]}</span></a></h2>
          <span class="a-price"><span class="a-offscreen">${item["price"]:.2f}</span></span>
          <span class="a-icon-alt">{item["rating"]} out of 5 stars</span>
          <span class="a-size-base s-underline-text">{item["reviews"]:,}</span>
        </div>
      </div>"""
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


def _walmart_product_html(next_data: dict[str, Any]) -> str:
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data)
        + "</script></body></html>"
    )


def _walmart_search_html(next_data: dict[str, Any]) -> str:
    return _walmart_product_html(next_data)


def _walmart_product_state(**overrides: Any) -> dict[str, Any]:
    product = {
        "usItemId": "12345678",
        "name": "Sony WH-1000XM5 Wireless Headphones",
        "priceInfo": {"currentPrice": {"price": 39900, "currencyUnit": "USD"}},
        "averageRating": 4.7,
        "seller": {"displayName": "Walmart.com"},
        "availabilityStatus": "IN_STOCK",
    }
    product.update(overrides)
    return {
        "props": {
            "pageProps": {
                "initialData": {"data": {"product": product}},
                "pageInfo": {
                    "canonicalUrl": "https://www.walmart.com/ip/Sony-WH-1000XM5-Wireless-Headphones/12345678"
                },
            }
        }
    }


def _walmart_search_state(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "props": {
            "pageProps": {
                "initialData": {
                    "searchResult": {
                        "itemStacks": [
                            {"items": items},
                        ]
                    }
                }
            }
        }
    }


def _tiktok_render_json(sold_count: int = 1200, price: int = 2999) -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "productInfo": {
                "title": "TikTok Trending Hoodie",
                "price": price,
                "soldCount": sold_count,
                "rating": {"value": 4.9},
                "shopName": "HoodieHQ",
            }
        },
    }


# ── Package surface ────────────────────────────────────────────────────


def test_marketplace_package_exports() -> None:
    assert set(_marketplace_pkg.__all__) == {
        "amazon_get_product",
        "amazon_search_products",
        "walmart_get_product",
        "walmart_search_products",
        "tiktok_get_product",
        "tiktok_get_trending",
    }
    # Per-module names stay importable (the MCP wiring layer uses these).
    assert callable(amazon.get_product)
    assert callable(amazon.search_products)
    assert callable(walmart.get_product)
    assert callable(walmart.search_products)
    assert callable(tiktok_shop.get_product)
    assert callable(tiktok_shop.get_trending)


# ── Amazon ─────────────────────────────────────────────────────────────


async def test_amazon_get_product_normalization() -> None:
    async with respx.mock:
        respx.get(AMAZON_PRODUCT_URL).mock(
            return_value=httpx.Response(200, text=_amazon_product_html())
        )
        result = await amazon.get_product("B0TEST1234")
    assert set(result) == AMAZON_SCHEMA_KEYS | {"_badges"}  # schema keys + non-contractual badges
    assert result["asin"] == "B0TEST1234"
    assert result["title"] == "Apple iPhone 15 Pro 128GB"
    assert result["price"] == 999.99
    assert result["currency"] == "USD"
    assert result["buy_box"] == "Apple"
    assert result["brand"] == "Apple"
    assert result["rating"] == 4.8
    assert result["review_count"] == 12345
    assert result["bsr"] == 87
    assert result["category"] == "Cell Phones & Accessories"
    assert result["offers"] == 14
    assert result["url"] == AMAZON_PRODUCT_URL
    assert result["_badges"] == ["Amazon's Choice"]


async def test_amazon_get_product_invalid_asin() -> None:
    assert await amazon.get_product("not-an-asin") == {}
    assert await amazon.get_product("") == {}


async def test_amazon_get_product_captcha_blocked() -> None:
    async with respx.mock:
        respx.get(AMAZON_PRODUCT_URL).mock(
            return_value=httpx.Response(
                200, text="<html>Enter the characters you see below. Robot Check captcha</html>"
            )
        )
        assert await amazon.get_product("B0TEST1234") == {}


async def test_amazon_get_product_http_500() -> None:
    async with respx.mock:
        respx.get(AMAZON_PRODUCT_URL).mock(return_value=httpx.Response(500, text="boom"))
        assert await amazon.get_product("B0TEST1234") == {}


async def test_amazon_get_product_transport_error() -> None:
    async with respx.mock:
        respx.get(AMAZON_PRODUCT_URL).mock(side_effect=httpx.ConnectError("boom"))
        assert await amazon.get_product("B0TEST1234") == {}


async def test_amazon_get_product_empty_page() -> None:
    async with respx.mock:
        respx.get(AMAZON_PRODUCT_URL).mock(
            return_value=httpx.Response(200, text="<html><body>nothing here</body></html>")
        )
        assert await amazon.get_product("B0TEST1234") == {}


async def test_amazon_search_products() -> None:
    items = [
        {
            "asin": "B0SEARCH01",
            "title": "iPhone Case Clear",
            "price": 19.99,
            "rating": 4.6,
            "reviews": 3210,
        },
        {
            "asin": "B0SEARCH02",
            "title": "USB-C Cable 2m",
            "price": 9.49,
            "rating": 4.4,
            "reviews": 87,
        },
        {
            "asin": "B0SEARCH03",
            "title": "Screen Protector",
            "price": 12.99,
            "rating": 4.1,
            "reviews": 500,
        },
    ]
    async with respx.mock:
        respx.get(AMAZON_SEARCH_URL).mock(
            return_value=httpx.Response(200, text=_amazon_search_html(items))
        )
        results = await amazon.search_products("iphone case", limit=2)
    assert len(results) == 2  # limit honored
    first = results[0]
    assert set(first) == AMAZON_SCHEMA_KEYS
    assert first["asin"] == "B0SEARCH01"
    assert first["title"] == "iPhone Case Clear"
    assert first["price"] == 19.99
    assert first["currency"] == "USD"
    assert first["rating"] == 4.6
    assert first["review_count"] == 3210
    assert first["url"].startswith("https://www.amazon.com/dp/B0SEARCH01")
    assert first["bsr"] == 0  # sparse defaults


async def test_amazon_search_empty_page() -> None:
    async with respx.mock:
        respx.get(AMAZON_SEARCH_URL).mock(
            return_value=httpx.Response(200, text="<html><body>No results</body></html>")
        )
        assert await amazon.search_products("zzzz") == []


async def test_amazon_search_empty_query() -> None:
    assert await amazon.search_products("") == []


async def test_amazon_robots_disallow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_MARKETPLACE_HONOR_ROBOTS", "1")
    async with respx.mock:
        respx.get(AMAZON_ROBOTS_URL).mock(
            return_value=httpx.Response(200, text="User-agent: *\nDisallow: /dp/\n")
        )
        product_route = respx.get(AMAZON_PRODUCT_URL).mock(
            return_value=httpx.Response(200, text=_amazon_product_html())
        )
        assert await amazon.get_product("B0TEST1234") == {}
        assert not product_route.called  # product page never fetched


# ── Walmart ────────────────────────────────────────────────────────────


async def test_walmart_get_product_next_data() -> None:
    async with respx.mock:
        respx.get(WALMART_PRODUCT_URL).mock(
            return_value=httpx.Response(200, text=_walmart_product_html(_walmart_product_state()))
        )
        result = await walmart.get_product("12345678")
    assert set(result) == WALMART_SCHEMA_KEYS
    assert result["product_id"] == "12345678"
    assert result["title"] == "Sony WH-1000XM5 Wireless Headphones"
    assert result["price"] == 399.0  # 39900 cents → $399.00
    assert result["currency"] == "USD"
    assert result["seller"] == "Walmart.com"
    assert result["rating"] == 4.7
    assert result["stock"] is True
    assert "walmart.com" in result["url"]


async def test_walmart_get_product_follows_redirect() -> None:
    async with respx.mock:
        respx.get(WALMART_PRODUCT_URL).mock(
            return_value=httpx.Response(
                302, headers={"location": "https://www.walmart.com/ip/Sony-Headphones/12345678"}
            )
        )
        respx.get("https://www.walmart.com/ip/Sony-Headphones/12345678").mock(
            return_value=httpx.Response(200, text=_walmart_product_html(_walmart_product_state()))
        )
        result = await walmart.get_product("12345678")
    assert result["title"] == "Sony WH-1000XM5 Wireless Headphones"


async def test_walmart_get_product_redux_fallback() -> None:
    redux = {
        "product": {
            "items": {
                "byId": {
                    "12345678": {
                        "usItemId": "12345678",
                        "name": "Redux Headphones",
                        "priceInfo": {"currentPrice": {"price": 7900, "currencyUnit": "USD"}},
                        "averageRating": 4.1,
                        "seller": {"displayName": "Sold by ThirdParty"},
                        "availabilityStatus": "OUT_OF_STOCK",
                    }
                }
            }
        }
    }
    html_text = (
        "<html><body><script>window.__WML_REDUX_INITIAL_STATE__ = "
        + json.dumps(redux)
        + ";</script></body></html>"
    )
    async with respx.mock:
        respx.get(WALMART_PRODUCT_URL).mock(return_value=httpx.Response(200, text=html_text))
        result = await walmart.get_product("12345678")
    assert result["title"] == "Redux Headphones"
    assert result["price"] == 79.0
    assert result["seller"] == "Sold by ThirdParty"
    assert result["stock"] is False


async def test_walmart_get_product_og_fallback() -> None:
    html_text = """<html><head>
    <meta property="og:title" content="OG Product Name">
    <meta property="og:price:amount" content="45.99">
    <meta property="og:price:currency" content="USD">
    <meta property="og:url" content="https://www.walmart.com/ip/OG-Product/12345678">
    </head><body></body></html>"""
    async with respx.mock:
        respx.get(WALMART_PRODUCT_URL).mock(return_value=httpx.Response(200, text=html_text))
        result = await walmart.get_product("12345678")
    assert result["title"] == "OG Product Name"
    assert result["price"] == 45.99
    assert result["url"] == "https://www.walmart.com/ip/OG-Product/12345678"


async def test_walmart_get_product_failure() -> None:
    async with respx.mock:
        respx.get(WALMART_PRODUCT_URL).mock(
            return_value=httpx.Response(404, text="<html>Not Found</html>")
        )
        assert await walmart.get_product("12345678") == {}


async def test_walmart_search_products() -> None:
    state = _walmart_search_state(
        [
            {
                "usItemId": "2001",
                "name": "4K TV 55in",
                "priceInfo": {"currentPrice": {"price": 29900, "currencyUnit": "USD"}},
                "averageRating": 4.2,
                "sellerName": "Walmart.com",
                "canonicalUrl": "https://www.walmart.com/ip/4K-TV-55in/2001",
            },
            {
                "usItemId": "2002",
                "name": "Laptop 16GB",
                "priceInfo": {"currentPrice": {"price": 89900, "currencyUnit": "USD"}},
                "averageRating": 4.6,
                "sellerName": "Walmart.com",
                "canonicalUrl": "https://www.walmart.com/ip/Laptop-16GB/2002",
            },
        ]
    )
    async with respx.mock:
        respx.get(WALMART_SEARCH_URL).mock(
            return_value=httpx.Response(200, text=_walmart_search_html(state))
        )
        results = await walmart.search_products("tv", limit=1)
    assert len(results) == 1
    assert set(results[0]) == WALMART_SCHEMA_KEYS
    assert results[0]["product_id"] == "2001"
    assert results[0]["title"] == "4K TV 55in"
    assert results[0]["price"] == 299.0
    assert results[0]["rating"] == 4.2


async def test_walmart_search_bad_state() -> None:
    async with respx.mock:
        respx.get(WALMART_SEARCH_URL).mock(
            return_value=httpx.Response(200, text="<html>not json</html>")
        )
        assert await walmart.search_products("tv") == []


async def test_walmart_search_empty_query() -> None:
    assert await walmart.search_products("") == []


# ── TikTok Shop ────────────────────────────────────────────────────────


async def test_tiktok_get_product_render() -> None:
    async with respx.mock:
        respx.get(TIKTOK_RENDER_URL).mock(
            return_value=httpx.Response(200, json=_tiktok_render_json(sold_count=1200, price=2999))
        )
        result = await tiktok_shop.get_product("9988776655")
    assert set(result) == TIKTOK_SCHEMA_KEYS
    assert result["product_id"] == "9988776655"
    assert result["title"] == "TikTok Trending Hoodie"
    assert result["price"] == 29.99  # 2999 cents → $29.99
    assert result["sold_count"] == 1200
    assert result["gmv_estimate"] == 35988.0  # baseline snapshot: sold * price
    assert result["rating"] == 4.9
    assert result["shop"] == "HoodieHQ"
    assert result["url"] == TIKTOK_PDP_URL


async def test_tiktok_gmv_delta_between_polls() -> None:
    async with respx.mock:
        respx.get(TIKTOK_RENDER_URL).mock(
            return_value=httpx.Response(200, json=_tiktok_render_json(sold_count=1200, price=2999))
        )
        first = await tiktok_shop.get_product("9988776655")
        respx.get(TIKTOK_RENDER_URL).mock(
            return_value=httpx.Response(200, json=_tiktok_render_json(sold_count=1500, price=2999))
        )
        second = await tiktok_shop.get_product("9988776655")
    assert first["gmv_estimate"] == 35988.0
    assert second["gmv_estimate"] == 8997.0  # delta (300) * $29.99


async def test_tiktok_get_product_og_fallback() -> None:
    async with respx.mock:
        respx.get(TIKTOK_RENDER_URL).mock(return_value=httpx.Response(404, text="not found"))
        respx.get(TIKTOK_PDP_URL).mock(
            return_value=httpx.Response(
                200,
                text="""<html><head>
                <meta property="og:title" content="OG TikTok Product">
                <meta property="og:price:amount" content="19.99">
                <meta property="og:price:currency" content="USD">
                <meta property="product:sale_count" content="500">
                </head><body></body></html>""",
            )
        )
        result = await tiktok_shop.get_product("9988776655")
    assert result["title"] == "OG TikTok Product"
    assert result["price"] == 19.99
    assert result["sold_count"] == 500
    assert result["gmv_estimate"] == 9995.0  # 500 * $19.99


async def test_tiktok_get_product_failure() -> None:
    async with respx.mock:
        respx.get(TIKTOK_RENDER_URL).mock(return_value=httpx.Response(500, text="boom"))
        respx.get(TIKTOK_PDP_URL).mock(return_value=httpx.Response(500, text="boom"))
        assert await tiktok_shop.get_product("9988776655") == {}


async def test_tiktok_get_product_empty_id() -> None:
    assert await tiktok_shop.get_product("") == {}


async def test_tiktok_trending_default_empty() -> None:
    async with respx.mock:
        respx.get(TIKTOK_TRENDING_URL).mock(return_value=httpx.Response(404, text="not found"))
        assert await tiktok_shop.get_trending() == []


async def test_tiktok_trending_transport_error() -> None:
    async with respx.mock:
        respx.get(TIKTOK_TRENDING_URL).mock(side_effect=httpx.ConnectError("boom"))
        assert await tiktok_shop.get_trending(limit=10) == []


async def test_tiktok_trending_placeholder_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_TIKTOK_TRENDING_PLACEHOLDER", "1")
    async with respx.mock:
        respx.get(TIKTOK_TRENDING_URL).mock(return_value=httpx.Response(404, text="not found"))
        results = await tiktok_shop.get_trending(limit=5)
    assert len(results) == 1
    assert results[0]["title"].startswith("[placeholder]")
    assert results[0]["product_id"] == ""
