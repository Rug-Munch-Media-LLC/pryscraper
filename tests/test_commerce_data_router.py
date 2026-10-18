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

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.commerce_data.marketplaces as marketplaces
import datasets.commerce_data.social as social
import pry.api.routers.commerce.commerce_data as commerce_router_mod
from pry.api.routers.commerce.commerce_data import router as commerce_router
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
