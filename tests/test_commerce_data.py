# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the commerce_data package (eBay / Etsy / AliExpress / Shopify + social).

Covers the eBay Finding/Shopping API XML parsing, Shopify products.json
mapping, Etsy __NEXT_DATA__ + JSON-LD extraction, AliExpress
``_dida_config_`` extraction, the social profile scrapers (Instagram /
TikTok / X / YouTube), the never-raise contract (missing API key, HTTP
errors, rate limits, malformed payloads, login walls all degrade to
[] / {} / partial data), and the /v1/commerce/* + /v1/social/* router
(200 + 502-degradation + 400/422 validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.commerce_data as commerce_data
import datasets.commerce_data.marketplaces as marketplaces
import datasets.commerce_data.social as social
import pry.api.routers.commerce_data as commerce_router_mod
from pry.api.routers.commerce_data import router as commerce_router
from pry.core.errors import PryError

_EBAY_FIND_URL = "https://svcs.ebay.com/services/search/FindingService/v1"
_EBAY_ITEM_URL = "https://open.api.ebay.com/shopping"
_SHOPIFY_URL = "https://example-store.myshopify.com/products.json"
_ETSY_SEARCH_URL = "https://www.etsy.com/search"
_ETSY_LISTING_URL = "https://www.etsy.com/listing/555"
_ALIEXPRESS_SEARCH_URL = "https://www.aliexpress.com/w/wholesale"
_ALIEXPRESS_ITEM_URL = "https://www.aliexpress.com/item/777.html"
_INSTAGRAM_URL = "https://www.instagram.com/testuser/"
_TIKTOK_URL = "https://www.tiktok.com/@testuser"
_X_URL = "https://x.com/testuser"
_YOUTUBE_URL = "https://www.youtube.com/@testuser"


@pytest.fixture(autouse=True)
def _hermetic_commerce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff sleeps so tests are hermetic and fast."""
    monkeypatch.setattr(marketplaces, "RETRY_BASE", 0.0)
    monkeypatch.setattr(marketplaces, "MAX_BACKOFF", 0.0)
    monkeypatch.setattr(marketplaces, "MAX_RETRIES", 0)
    monkeypatch.setattr(social, "RETRY_BASE", 0.0)
    monkeypatch.setattr(social, "MAX_BACKOFF", 0.0)
    monkeypatch.setattr(social, "MAX_RETRIES", 0)


# ── fixtures ───────────────────────────────────────────────────────────


def _ebay_search_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<findItemsByKeywordsResponse xmlns="http://www.ebay.com/marketplace/search/v1/services">
  <ack>Success</ack>
  <searchResult count="1">
    <item>
      <itemId>123456789</itemId>
      <title>Test Widget Pro</title>
      <viewItemURL>https://www.ebay.com/itm/123456789</viewItemURL>
      <sellingStatus>
        <convertedCurrentPrice currencyId="USD">19.99</convertedCurrentPrice>
      </sellingStatus>
      <sellerInfo>
        <sellerUserName>top-seller</sellerUserName>
        <feedbackScore>4321</feedbackScore>
      </sellerInfo>
    </item>
  </searchResult>
  <paginationOutput><totalEntries>1</totalEntries></paginationOutput>
</findItemsByKeywordsResponse>
"""


def _ebay_item_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<GetSingleItemResponse xmlns="http://open.api.ebay.com/shopping">
  <Ack>Success</Ack>
  <Item>
    <ItemID>123456789</ItemID>
    <Title>Test Widget Pro</Title>
    <ViewItemURLForNaturalSearch>https://www.ebay.com/itm/123456789</ViewItemURLForNaturalSearch>
    <ConvertedCurrentPrice currencyID="USD">19.99</ConvertedCurrentPrice>
    <Seller>
      <UserID>top-seller</UserID>
      <FeedbackScore>4321</FeedbackScore>
    </Seller>
  </Item>
</GetSingleItemResponse>
"""


def _shopify_json() -> dict[str, Any]:
    return {
        "products": [
            {"id": 101, "title": "Widget", "handle": "widget", "variants": [{"price": "9.99"}]},
            {"id": 102, "title": "Gadget", "handle": "gadget", "variants": [{"price": "12.50"}]},
        ]
    }


def _etsy_search_html() -> str:
    data = {
        "props": {
            "pageProps": {
                "mainData": {
                    "listingData": [
                        {
                            "listing_id": 555,
                            "title": "Handmade Mug",
                            "price": {"amount": 1999, "divisor": 100, "currency_code": "USD"},
                            "shop_name": "MyShop",
                        }
                    ]
                }
            }
        }
    }
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(data)
        + "</script></head><body></body></html>"
    )


def _etsy_listing_html() -> str:
    return """<html><head>
<meta property="og:title" content="Handmade Mug by MyShop"/>
<meta property="og:url" content="https://www.etsy.com/listing/555"/>
<meta property="og:description" content="A handmade mug."/>
<script type="application/ld+json">{"@type":"Product","name":"Handmade Mug","offers":{"@type":"Offer","price":"19.99","priceCurrency":"USD"}}</script>
</head><body><a href="/shop/MyShop">MyShop</a></body></html>"""


def _aliexpress_search_html() -> str:
    return (
        "<html><body><script>"
        'window._dida_config_={"data":[{"productId":777,"subject":"Cool Gadget",'
        '"formatedPrice":"US $24.99","storeName":"SuperStore"}]};'
        "</script></body></html>"
    )


def _aliexpress_item_html() -> str:
    return (
        "<html><body><script>"
        'window.runParams = {"data": {"price": {"formatedPrice": "$24.99"}, '
        '"subject": "Cool Gadget"}};'
        "</script></body></html>"
    )


def _instagram_html() -> str:
    return (
        '<html><head><meta property="og:description" content="1.2M Followers, '
        "345 Following, 1,234 Posts - See Instagram photos and videos from "
        'testuser"/></head><body></body></html>'
    )


def _tiktok_html() -> str:
    data = {
        "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
                "userInfo": {
                    "stats": {
                        "followerCount": 100000,
                        "followingCount": 50,
                        "heartCount": 500000,
                        "videoCount": 100,
                    }
                }
            }
        }
    }
    return (
        '<html><head><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" '
        'type="application/json">' + json.dumps(data) + "</script></head><body></body></html>"
    )


def _twitter_html() -> str:
    return (
        '<html><head><meta property="og:description" content="10K Followers, '
        '200 Following, 5K Posts - See tweets from testuser"/></head>'
        "<body></body></html>"
    )


def _youtube_html() -> str:
    return (
        "<html><head><script>var ytInitialData = {"
        '"subscriberCountText":{"content":"1.23M subscribers"},'
        '"videoCountText":{"content":"456 videos"},'
        '"viewCountText":{"content":"50,000,000 views"}};</script>'
        "</head><body></body></html>"
    )


# ── package / import surface ───────────────────────────────────────────


def test_package_imports() -> None:
    assert hasattr(commerce_data, "search_product")
    assert hasattr(commerce_data, "get_product")
    assert hasattr(commerce_data, "get_social_metrics")
    assert hasattr(commerce_router_mod, "router")


# ── eBay ───────────────────────────────────────────────────────────────


@respx.mock
async def test_ebay_search_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplaces, "_api_key", lambda: "test-key")
    respx.get(url__startswith=_EBAY_FIND_URL).mock(
        return_value=httpx.Response(200, text=_ebay_search_xml())
    )
    results = await marketplaces.search_product("widget", marketplace="ebay")
    assert len(results) == 1
    assert results[0]["id"] == "123456789"
    assert results[0]["title"] == "Test Widget Pro"
    assert results[0]["price"] == 19.99
    assert results[0]["currency"] == "USD"
    assert results[0]["seller"] == "top-seller"
    assert results[0]["rating"] == 4321.0
    assert results[0]["marketplace"] == "ebay"


@respx.mock
async def test_ebay_search_no_key_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplaces, "_api_key", lambda: "")
    assert await marketplaces.search_product("widget", marketplace="ebay") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_ebay_search_http_error_returns_empty() -> None:
    respx.get(url__startswith=_EBAY_FIND_URL).mock(return_value=httpx.Response(500))
    assert await marketplaces.search_product("widget", marketplace="ebay") == []


@respx.mock
async def test_ebay_search_malformed_xml_returns_empty() -> None:
    respx.get(url__startswith=_EBAY_FIND_URL).mock(
        return_value=httpx.Response(200, text="<not-valid-xml")
    )
    assert await marketplaces.search_product("widget", marketplace="ebay") == []


@respx.mock
async def test_ebay_search_ack_failure_returns_empty() -> None:
    body = _ebay_search_xml().replace("<ack>Success</ack>", "<ack>Failure</ack>")
    respx.get(url__startswith=_EBAY_FIND_URL).mock(return_value=httpx.Response(200, text=body))
    assert await marketplaces.search_product("widget", marketplace="ebay") == []


@respx.mock
async def test_ebay_get_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplaces, "_api_key", lambda: "test-key")
    respx.get(url__startswith=_EBAY_ITEM_URL).mock(
        return_value=httpx.Response(200, text=_ebay_item_xml())
    )
    product = await marketplaces.get_product("123456789", marketplace="ebay")
    assert product["id"] == "123456789"
    assert product["title"] == "Test Widget Pro"
    assert product["price"] == 19.99
    assert product["seller"] == "top-seller"


@respx.mock
async def test_ebay_get_not_found_returns_empty() -> None:
    body = _ebay_item_xml().replace("<Ack>Success</Ack>", "<Ack>Failure</Ack>")
    respx.get(url__startswith=_EBAY_ITEM_URL).mock(return_value=httpx.Response(200, text=body))
    assert await marketplaces.get_product("999", marketplace="ebay") == {}


@respx.mock
async def test_ebay_get_no_key_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(marketplaces, "_api_key", lambda: "")
    assert await marketplaces.get_product("123456789", marketplace="ebay") == {}


# ── Shopify ────────────────────────────────────────────────────────────


@respx.mock
async def test_shopify_search_success() -> None:
    respx.get(url__startswith=_SHOPIFY_URL).mock(
        return_value=httpx.Response(200, json=_shopify_json())
    )
    results = await marketplaces.search_product("example-store", marketplace="shopify")
    assert len(results) == 2
    assert results[0]["id"] == "101"
    assert results[0]["title"] == "Widget"
    assert results[0]["price"] == 9.99
    assert results[0]["seller"] == "example-store"
    assert results[0]["currency"] is None
    assert results[0]["url"] == "https://example-store.myshopify.com/products/widget"


@respx.mock
async def test_shopify_search_truncates_to_limit() -> None:
    respx.get(url__startswith=_SHOPIFY_URL).mock(
        return_value=httpx.Response(200, json=_shopify_json())
    )
    results = await marketplaces.search_product("example-store", marketplace="shopify", limit=1)
    assert len(results) == 1
    assert results[0]["id"] == "101"


@respx.mock
async def test_shopify_search_invalid_store_returns_empty() -> None:
    assert await marketplaces.search_product("bad store!", marketplace="shopify") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_shopify_search_http_error_returns_empty() -> None:
    respx.get(url__startswith=_SHOPIFY_URL).mock(return_value=httpx.Response(404))
    assert await marketplaces.search_product("example-store", marketplace="shopify") == []


@respx.mock
async def test_shopify_get_by_id() -> None:
    respx.get(url__startswith=_SHOPIFY_URL).mock(
        return_value=httpx.Response(200, json=_shopify_json())
    )
    product = await marketplaces.get_product("example-store:102", marketplace="shopify")
    assert product["id"] == "102"
    assert product["title"] == "Gadget"


@respx.mock
async def test_shopify_get_by_handle() -> None:
    respx.get(url__startswith=_SHOPIFY_URL).mock(
        return_value=httpx.Response(200, json=_shopify_json())
    )
    product = await marketplaces.get_product("example-store:widget", marketplace="shopify")
    assert product["id"] == "101"


@respx.mock
async def test_shopify_get_not_found_returns_empty() -> None:
    respx.get(url__startswith=_SHOPIFY_URL).mock(
        return_value=httpx.Response(200, json=_shopify_json())
    )
    assert await marketplaces.get_product("example-store:999", marketplace="shopify") == {}


async def test_shopify_get_missing_store_returns_empty() -> None:
    # public contract: no store prefix -> {}
    assert await marketplaces.get_product("102", marketplace="shopify") == {}


# ── Etsy ───────────────────────────────────────────────────────────────


@respx.mock
async def test_etsy_search_success() -> None:
    respx.get(url__startswith=_ETSY_SEARCH_URL).mock(
        return_value=httpx.Response(200, text=_etsy_search_html())
    )
    results = await marketplaces.search_product("mug", marketplace="etsy")
    assert len(results) == 1
    assert results[0]["id"] == "555"
    assert results[0]["title"] == "Handmade Mug"
    assert results[0]["price"] == 19.99
    assert results[0]["currency"] == "USD"
    assert results[0]["seller"] == "MyShop"


@respx.mock
async def test_etsy_search_http_error_returns_empty() -> None:
    respx.get(url__startswith=_ETSY_SEARCH_URL).mock(return_value=httpx.Response(403))
    assert await marketplaces.search_product("mug", marketplace="etsy") == []


@respx.mock
async def test_etsy_search_no_listings_returns_empty() -> None:
    html = _etsy_search_html().replace("listing_id", "other_key")
    respx.get(url__startswith=_ETSY_SEARCH_URL).mock(return_value=httpx.Response(200, text=html))
    assert await marketplaces.search_product("mug", marketplace="etsy") == []


@respx.mock
async def test_etsy_get_success() -> None:
    respx.get(url__startswith=_ETSY_LISTING_URL).mock(
        return_value=httpx.Response(200, text=_etsy_listing_html())
    )
    product = await marketplaces.get_product("555", marketplace="etsy")
    assert product["id"] == "555"
    assert product["title"] == "Handmade Mug by MyShop"
    assert product["price"] == 19.99
    assert product["currency"] == "USD"
    assert product["seller"] == "MyShop"


@respx.mock
async def test_etsy_get_http_error_returns_empty() -> None:
    respx.get(url__startswith=_ETSY_LISTING_URL).mock(return_value=httpx.Response(403))
    assert await marketplaces.get_product("555", marketplace="etsy") == {}


# ── AliExpress ─────────────────────────────────────────────────────────


@respx.mock
async def test_aliexpress_search_success() -> None:
    respx.get(url__startswith=_ALIEXPRESS_SEARCH_URL).mock(
        return_value=httpx.Response(200, text=_aliexpress_search_html())
    )
    results = await marketplaces.search_product("gadget", marketplace="aliexpress")
    assert len(results) == 1
    assert results[0]["id"] == "777"
    assert results[0]["title"] == "Cool Gadget"
    assert results[0]["price"] == 24.99
    assert results[0]["seller"] == "SuperStore"


@respx.mock
async def test_aliexpress_search_challenge_returns_empty() -> None:
    # AliExpress frequently serves a JS challenge page with no config JSON.
    respx.get(url__startswith=_ALIEXPRESS_SEARCH_URL).mock(
        return_value=httpx.Response(200, text="<html><body>verify...</body></html>")
    )
    assert await marketplaces.search_product("gadget", marketplace="aliexpress") == []


@respx.mock
async def test_aliexpress_get_success() -> None:
    respx.get(url__startswith=_ALIEXPRESS_ITEM_URL).mock(
        return_value=httpx.Response(200, text=_aliexpress_item_html())
    )
    product = await marketplaces.get_product("777", marketplace="aliexpress")
    assert product["id"] == "777"
    assert product["title"] == "Cool Gadget"
    assert product["price"] == 24.99


@respx.mock
async def test_aliexpress_get_http_error_returns_empty() -> None:
    respx.get(url__startswith=_ALIEXPRESS_ITEM_URL).mock(return_value=httpx.Response(403))
    assert await marketplaces.get_product("777", marketplace="aliexpress") == {}


# ── marketplace contract edge cases ────────────────────────────────────


async def test_search_unknown_marketplace_returns_empty() -> None:
    assert await marketplaces.search_product("x", marketplace="walmart") == []


async def test_get_unknown_marketplace_returns_empty() -> None:
    assert await marketplaces.get_product("1", marketplace="walmart") == {}


async def test_search_empty_query_returns_empty() -> None:
    assert await marketplaces.search_product("") == []
    assert await marketplaces.search_product("   ") == []


async def test_get_empty_id_returns_empty() -> None:
    assert await marketplaces.get_product("") == {}


async def test_limit_is_clamped() -> None:
    assert marketplaces._clamp_limit(0) == 1
    assert marketplaces._clamp_limit(-5) == 1
    assert marketplaces._clamp_limit(10000) == 250
    assert marketplaces._clamp_limit("abc") == 20


# ── social: Instagram ──────────────────────────────────────────────────


@respx.mock
async def test_instagram_metrics_success() -> None:
    respx.get(url__startswith=_INSTAGRAM_URL).mock(
        return_value=httpx.Response(200, text=_instagram_html())
    )
    metrics = await social.get_social_metrics("testuser", platform="instagram")
    assert metrics["handle"] == "testuser"
    assert metrics["platform"] == "instagram"
    assert metrics["followers"] == 1_200_000
    assert metrics["following"] == 345
    assert metrics["posts"] == 1234
    assert metrics["avg_engagement"] is None
    assert metrics["engagement_rate"] is None
    assert metrics["fake_follower_estimate"] is None


@respx.mock
async def test_instagram_login_wall_returns_partial() -> None:
    respx.get(url__startswith=_INSTAGRAM_URL).mock(
        return_value=httpx.Response(200, text="<html><body>login wall</body></html>")
    )
    metrics = await social.get_social_metrics("testuser", platform="instagram")
    assert metrics["followers"] is None
    assert metrics["following"] is None
    assert metrics["posts"] is None
    assert metrics["handle"] == "testuser"  # partial data, not an error


@respx.mock
async def test_social_http_error_returns_partial() -> None:
    respx.get(url__startswith=_INSTAGRAM_URL).mock(return_value=httpx.Response(404))
    metrics = await social.get_social_metrics("nobody", platform="instagram")
    assert metrics["handle"] == "nobody"
    assert metrics["followers"] is None


# ── social: TikTok ─────────────────────────────────────────────────────


@respx.mock
async def test_tiktok_metrics_success() -> None:
    respx.get(url__startswith=_TIKTOK_URL).mock(
        return_value=httpx.Response(200, text=_tiktok_html())
    )
    metrics = await social.get_social_metrics("testuser", platform="tiktok")
    assert metrics["followers"] == 100000
    assert metrics["following"] == 50
    assert metrics["posts"] == 100
    assert metrics["avg_engagement"] == 5000.0  # 500k hearts / 100 videos
    assert metrics["engagement_rate"] == 0.05
    assert metrics["fake_follower_estimate"] == 0.05


@respx.mock
async def test_tiktok_challenge_returns_partial() -> None:
    respx.get(url__startswith=_TIKTOK_URL).mock(
        return_value=httpx.Response(200, text="<html><body>challenge</body></html>")
    )
    metrics = await social.get_social_metrics("testuser", platform="tiktok")
    assert metrics["followers"] is None
    assert metrics["avg_engagement"] is None


# ── social: X / Twitter ────────────────────────────────────────────────


@respx.mock
async def test_twitter_metrics_success() -> None:
    respx.get(url__startswith=_X_URL).mock(return_value=httpx.Response(200, text=_twitter_html()))
    metrics = await social.get_social_metrics("testuser", platform="twitter")
    assert metrics["followers"] == 10000
    assert metrics["following"] == 200
    assert metrics["posts"] == 5000
    assert metrics["platform"] == "twitter"


@respx.mock
async def test_x_metrics_alias() -> None:
    respx.get(url__startswith=_X_URL).mock(return_value=httpx.Response(200, text=_twitter_html()))
    metrics = await social.get_social_metrics("testuser", platform="x")
    assert metrics["followers"] == 10000
    assert metrics["platform"] == "x"


# ── social: YouTube ────────────────────────────────────────────────────


@respx.mock
async def test_youtube_metrics_success() -> None:
    respx.get(url__startswith=_YOUTUBE_URL).mock(
        return_value=httpx.Response(200, text=_youtube_html())
    )
    metrics = await social.get_social_metrics("testuser", platform="youtube")
    assert metrics["followers"] == 1_230_000
    assert metrics["posts"] == 456
    assert metrics["avg_engagement"] == round(50_000_000 / 456, 2)
    assert metrics["following"] is None


# ── social contract edge cases ─────────────────────────────────────────


async def test_social_unknown_platform_returns_empty() -> None:
    assert await social.get_social_metrics("testuser", platform="linkedin") == {}


async def test_social_empty_handle_returns_empty() -> None:
    assert await social.get_social_metrics("", platform="instagram") == {}


@respx.mock
async def test_social_handle_strips_at_prefix() -> None:
    respx.get(url__startswith=_TIKTOK_URL).mock(
        return_value=httpx.Response(200, text=_tiktok_html())
    )
    metrics = await social.get_social_metrics("@testuser", platform="tiktok")
    assert metrics["handle"] == "testuser"


def test_estimate_fake_followers_bands() -> None:
    assert social.estimate_fake_followers(1000, 100) == 0.05  # 10% engagement
    assert social.estimate_fake_followers(1000, 1) == 0.70  # 0.1% engagement
    assert social.estimate_fake_followers(1000, 0) == 0.90  # ~0% engagement
    assert social.estimate_fake_followers(None, 10) is None
    assert social.estimate_fake_followers(1000, None) is None


# ── router ─────────────────────────────────────────────────────────────


@pytest.fixture
def commerce_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(commerce_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_importable() -> None:
    assert hasattr(commerce_router_mod, "router")
    assert hasattr(commerce_router_mod, "_commerce_module")


def test_router_commerce_search_success(
    commerce_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(query: str, marketplace: str = "ebay", limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": "1", "title": f"{query} on {marketplace}", "marketplace": marketplace}]

    monkeypatch.setattr(marketplaces, "search_product", fake)
    resp = _client(commerce_app).get(
        "/v1/commerce/search", params={"query": "widget", "marketplace": "ebay", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["marketplace"] == "ebay"
    assert body["data"][0]["title"] == "widget on ebay"


def test_router_commerce_get_success(
    commerce_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(product_id: str, marketplace: str = "ebay") -> dict[str, Any]:
        return {"id": product_id, "title": "Widget", "marketplace": marketplace}

    monkeypatch.setattr(marketplaces, "get_product", fake)
    resp = _client(commerce_app).get("/v1/commerce/ebay/123456789")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "123456789"


def test_router_social_success(commerce_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(handle: str, platform: str = "instagram") -> dict[str, Any]:
        return {"handle": handle, "platform": platform, "followers": 100}

    monkeypatch.setattr(social, "get_social_metrics", fake)
    resp = _client(commerce_app).get("/v1/social/instagram/testuser")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["followers"] == 100


def test_router_502_when_module_absent(
    commerce_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commerce_router_mod, "_commerce_module", lambda name: None)
    assert (
        _client(commerce_app).get("/v1/commerce/search", params={"query": "x"}).status_code == 502
    )
    assert _client(commerce_app).get("/v1/commerce/ebay/123").status_code == 502
    assert _client(commerce_app).get("/v1/social/instagram/user").status_code == 502


def test_router_validation(commerce_app: FastAPI) -> None:
    # 400: unsupported marketplace / platform
    assert (
        _client(commerce_app)
        .get("/v1/commerce/search", params={"query": "x", "marketplace": "amazon"})
        .status_code
        == 400
    )
    assert _client(commerce_app).get("/v1/commerce/walmart/123").status_code == 400
    assert _client(commerce_app).get("/v1/social/linkedin/user").status_code == 400
    # 422: missing/empty required params, out-of-range limit
    assert _client(commerce_app).get("/v1/commerce/search").status_code == 422
    assert _client(commerce_app).get("/v1/commerce/search", params={"query": ""}).status_code == 422
    assert (
        _client(commerce_app)
        .get("/v1/commerce/search", params={"query": "x", "limit": 0})
        .status_code
        == 422
    )
    assert (
        _client(commerce_app)
        .get("/v1/commerce/search", params={"query": "x", "limit": 251})
        .status_code
        == 422
    )
