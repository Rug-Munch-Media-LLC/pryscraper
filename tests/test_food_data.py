# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the food_data package (grocery prices + restaurant menus).

Covers the Kroger OAuth client-credentials flow + product search, the
Walmart search-page scrape fallback (REDUX JSON + signature regex), the
restaurant menu scrape (DuckDuckGo search -> JSON-LD extraction -> HTML
price fallback), the never-raise contract (HTTP errors and malformed
payloads degrade to ``[]`` / ``{}``), and the /v1/food/* router (200 +
502-degradation + 422 validation).

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

import food_data
import food_data.grocery as grocery
import food_data.restaurants as restaurants
import routers.food_data as food_router_mod
from pry.core.errors import PryError
from routers.food_data import router as food_router

_KROGER_OAUTH_URL = "https://api.kroger.com/v1/connect/oauth2/token"
_KROGER_PRODUCTS_URL = "https://api.kroger.com/v1/products"
_WALMART_URL = "https://www.walmart.com/search"
_INSTACART_URL = "https://www.instacart.com/store/s"
_ALDI_URL = "https://www.aldi.us/en/search"
_DDG_URL = "https://html.duckduckgo.com/html/"
_MENU_URL = "https://example.com/menu"
_LANDING_URL = "https://example.com/"


@pytest.fixture(autouse=True)
def _hermetic_food(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove Kroger keys and drop the token cache so tests are deterministic."""
    monkeypatch.delenv("PRY_KROGER_CLIENT_ID", raising=False)
    monkeypatch.delenv("PRY_KROGER_CLIENT_SECRET", raising=False)
    grocery._clear_token_cache()


# ── Payload fixtures ───────────────────────────────────────────────────


def _kroger_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "productId": "0001111043112",
                "description": "Milk",
                "items": [
                    {
                        "itemId": "1",
                        "price": {"regular": 3.49, "promo": None},
                        "size": "1 GAL",
                        "soldBy": "EA",
                    }
                ],
            },
            {
                "productId": "0000000004011",
                "description": "Bananas",
                "items": [
                    {
                        "itemId": "2",
                        "price": {"regular": 0.58},
                        "size": "1 LB",
                        "soldBy": "LB",
                    }
                ],
            },
        ]
    }


def _kroger_token_payload() -> dict[str, Any]:
    return {"access_token": "test-token-123", "expires_in": 1800, "token_type": "bearer"}


def _walmart_html() -> str:
    data: dict[str, Any] = {
        "productSearchPage": {
            "products": [
                {
                    "name": "Great Value 2% Milk, Gallon",
                    "price": {"currentPrice": 2.98, "currencyUnit": "USD"},
                },
                {
                    "name": "Bananas, per lb",
                    "price": {"currentPrice": 0.58, "currencyUnit": "USD"},
                },
            ]
        }
    }
    return (
        "<html><head></head><body><script>window.__WML_REDUX_INITIAL_STATE__ = "
        + json.dumps(data)
        + ";</script></body></html>"
    )


def _walmart_regex_html() -> str:
    # No REDUX blob: exercises the signature regex fallback (nested braces).
    return (
        '<html><body><div>{"name": "Milk 1 gal", "price": '
        '{"currentPrice": 3.12, "currencyUnit": "USD"}}</div></body></html>'
    )


def _instacart_apollo_html() -> str:
    data: dict[str, Any] = {
        "ROOT_QUERY": {
            "searchResults": [
                {"name": "Organic Whole Milk, Half Gallon", "price": {"amount": 4.29}},
                {"name": "Bananas, per lb", "price": {"amount": 0.69}},
            ]
        }
    }
    return (
        "<html><head></head><body><script>window.__APOLLO_STATE__ = "
        + json.dumps(data)
        + ";</script></body></html>"
    )


def _instacart_jsonld_html() -> str:
    return """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Organic Milk","offers":{"price":"4.49","priceCurrency":"USD"}}
</script></head><body></body></html>"""


def _aldi_jsonld_html() -> str:
    return """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Simply Nature Organic Milk","offers":{"price":"3.99","priceCurrency":"USD"}}
</script></head><body></body></html>"""


def _ddg_html(*urls: str) -> str:
    links = "\n".join(f'<a class="result__a" href="{url}">{url}</a>' for url in urls)
    return f"<html><body>{links}</body></html>"


_JSONLD_MENU_PAGE = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Menu","name":"Dinner Menu","hasMenuSection":[
  {"@type":"MenuSection","name":"Starters","hasMenuItems":[
    {"@type":"MenuItem","name":"Calamari","description":"Crispy squid","offers":{"price":"11.50","priceCurrency":"USD"}},
    {"@type":"MenuItem","name":"Garlic Bread","offers":{"price":6.00}}
  ]}
]}
</script></head><body></body></html>"""

_HTML_MENU_PAGE = """<html><head><title>Joe's Diner</title></head><body>
<h1>Joe's Diner</h1>
<h2>Burgers</h2>
<ul><li>Classic Burger $12.99</li><li>Bacon Burger $14.50</li></ul>
<h2>Drinks</h2>
<ul><li>Milkshake $5.00</li></ul>
</body></html>"""


# ── package / import surface ───────────────────────────────────────────


def test_package_imports() -> None:
    assert hasattr(food_data, "get_grocery_prices")
    assert hasattr(food_data, "get_restaurant_menu")
    assert hasattr(food_router_mod, "router")


# ── grocery: Kroger ────────────────────────────────────────────────────


@respx.mock
async def test_kroger_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_KROGER_CLIENT_ID", "test-id")
    monkeypatch.setenv("PRY_KROGER_CLIENT_SECRET", "test-secret")
    respx.post(_KROGER_OAUTH_URL).mock(
        return_value=httpx.Response(200, json=_kroger_token_payload())
    )
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(
        return_value=httpx.Response(200, json=_kroger_payload())
    )
    results = await grocery.get_grocery_prices("milk", "45202", limit=20)
    assert len(results) == 2
    first = results[0]
    assert first["product"] == "Milk"
    assert first["store"] == "Kroger"
    assert first["price"] == 3.49
    assert first["currency"] == "USD"
    assert first["zip_code"] == "45202"
    assert first["unit"] == "1 GAL"
    assert first["date"]


@respx.mock
async def test_kroger_token_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_KROGER_CLIENT_ID", "test-id")
    monkeypatch.setenv("PRY_KROGER_CLIENT_SECRET", "test-secret")
    respx.post(_KROGER_OAUTH_URL).mock(
        return_value=httpx.Response(200, json=_kroger_token_payload())
    )
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(
        return_value=httpx.Response(200, json=_kroger_payload())
    )
    await grocery.get_grocery_prices("milk", "45202")
    await grocery.get_grocery_prices("bananas", "45202")
    token_calls = [c for c in respx.calls if str(c.request.url).startswith(_KROGER_OAUTH_URL)]
    assert len(token_calls) == 1


@respx.mock
async def test_kroger_no_keys_uses_walmart_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # No Kroger keys configured: Kroger is skipped, the keyless Walmart
    # scrape fallback still runs (and returns results).
    monkeypatch.setenv("PRY_KROGER_CLIENT_ID", "")
    monkeypatch.setenv("PRY_KROGER_CLIENT_SECRET", "")
    respx.get(url__startswith=_WALMART_URL).mock(
        return_value=httpx.Response(200, text=_walmart_html())
    )
    results = await grocery.get_grocery_prices("milk", "45202")
    assert results
    assert results[0]["store"] == "Walmart"


@respx.mock
async def test_grocery_invalid_zip_returns_empty() -> None:
    assert await grocery.get_grocery_prices("milk", "45") == []
    assert await grocery.get_grocery_prices("milk", "") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_grocery_blank_query_returns_empty() -> None:
    assert await grocery.get_grocery_prices("   ", "45202") == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_grocery_limit_zero_returns_empty() -> None:
    assert await grocery.get_grocery_prices("milk", "45202", limit=0) == []
    assert respx.calls.call_count == 0


# ── grocery: Walmart fallback ──────────────────────────────────────────


@respx.mock
async def test_kroger_token_error_falls_back_walmart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_KROGER_CLIENT_ID", "test-id")
    monkeypatch.setenv("PRY_KROGER_CLIENT_SECRET", "test-secret")
    respx.post(_KROGER_OAUTH_URL).mock(return_value=httpx.Response(401))
    respx.get(url__startswith=_WALMART_URL).mock(
        return_value=httpx.Response(200, text=_walmart_html())
    )
    results = await grocery.get_grocery_prices("milk", "45202")
    assert len(results) == 2
    assert results[0]["store"] == "Walmart"
    assert results[0]["price"] == 2.98
    assert results[0]["unit"] == "each"


@respx.mock
async def test_kroger_http_error_falls_back_walmart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_KROGER_CLIENT_ID", "test-id")
    monkeypatch.setenv("PRY_KROGER_CLIENT_SECRET", "test-secret")
    respx.post(_KROGER_OAUTH_URL).mock(
        return_value=httpx.Response(200, json=_kroger_token_payload())
    )
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_WALMART_URL).mock(
        return_value=httpx.Response(200, text=_walmart_html())
    )
    results = await grocery.get_grocery_prices("milk", "45202")
    assert results
    assert results[0]["store"] == "Walmart"


@respx.mock
async def test_kroger_empty_data_falls_back_walmart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_KROGER_CLIENT_ID", "test-id")
    monkeypatch.setenv("PRY_KROGER_CLIENT_SECRET", "test-secret")
    respx.post(_KROGER_OAUTH_URL).mock(
        return_value=httpx.Response(200, json=_kroger_token_payload())
    )
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(url__startswith=_WALMART_URL).mock(
        return_value=httpx.Response(200, text=_walmart_html())
    )
    results = await grocery.get_grocery_prices("milk", "45202")
    assert results
    assert results[0]["store"] == "Walmart"


@respx.mock
async def test_kroger_malformed_then_walmart_fails_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRY_KROGER_CLIENT_ID", "test-id")
    monkeypatch.setenv("PRY_KROGER_CLIENT_SECRET", "test-secret")
    respx.post(_KROGER_OAUTH_URL).mock(
        return_value=httpx.Response(200, json=_kroger_token_payload())
    )
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(
        return_value=httpx.Response(200, json={"nope": 1})
    )
    respx.get(url__startswith=_WALMART_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_INSTACART_URL).mock(return_value=httpx.Response(403))
    respx.get(url__startswith=_ALDI_URL).mock(return_value=httpx.Response(403))
    assert await grocery.get_grocery_prices("milk", "45202") == []


@respx.mock
async def test_walmart_redux_scrape_success() -> None:
    respx.get(url__startswith=_WALMART_URL).mock(
        return_value=httpx.Response(200, text=_walmart_html())
    )
    results = await grocery.get_grocery_prices("milk", "45202")
    assert len(results) == 2
    assert results[0]["store"] == "Walmart"
    assert results[0]["product"] == "Great Value 2% Milk, Gallon"
    assert results[0]["currency"] == "USD"


@respx.mock
async def test_walmart_regex_fallback() -> None:
    respx.get(url__startswith=_WALMART_URL).mock(
        return_value=httpx.Response(200, text=_walmart_regex_html())
    )
    results = await grocery.get_grocery_prices("milk", "45202")
    assert len(results) == 1
    assert results[0]["product"] == "Milk 1 gal"
    assert results[0]["price"] == 3.12


@respx.mock
async def test_walmart_http_error_returns_empty() -> None:
    respx.get(url__startswith=_WALMART_URL).mock(return_value=httpx.Response(403))
    respx.get(url__startswith=_INSTACART_URL).mock(return_value=httpx.Response(403))
    respx.get(url__startswith=_ALDI_URL).mock(return_value=httpx.Response(403))
    assert await grocery.get_grocery_prices("milk", "45202") == []


# ── grocery: Instacart fallback ────────────────────────────────────────


@respx.mock
async def test_instacart_apollo_scrape_success() -> None:
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_WALMART_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_INSTACART_URL).mock(
        return_value=httpx.Response(200, text=_instacart_apollo_html())
    )
    results = await grocery.get_grocery_prices("milk", "45202")
    assert len(results) == 2
    first = results[0]
    assert first["store"] == "Instacart"
    assert first["product"] == "Organic Whole Milk, Half Gallon"
    assert first["price"] == 4.29
    assert first["currency"] == "USD"


@respx.mock
async def test_instacart_jsonld_scrape_success() -> None:
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_WALMART_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_INSTACART_URL).mock(
        return_value=httpx.Response(200, text=_instacart_jsonld_html())
    )
    results = await grocery.get_grocery_prices("milk", "45202")
    assert len(results) == 1
    assert results[0]["store"] == "Instacart"
    assert results[0]["product"] == "Organic Milk"
    assert results[0]["price"] == 4.49


@respx.mock
async def test_instacart_http_error_returns_empty() -> None:
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_WALMART_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_INSTACART_URL).mock(return_value=httpx.Response(403))
    respx.get(url__startswith=_ALDI_URL).mock(return_value=httpx.Response(403))
    assert await grocery.get_grocery_prices("milk", "45202") == []


# ── grocery: Aldi / regional fallback ──────────────────────────────────


@respx.mock
async def test_aldi_jsonld_scrape_success() -> None:
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_WALMART_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_INSTACART_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_ALDI_URL).mock(
        return_value=httpx.Response(200, text=_aldi_jsonld_html())
    )
    results = await grocery.get_grocery_prices("milk", "45202")
    assert len(results) == 1
    first = results[0]
    assert first["store"] == "Aldi"
    assert first["product"] == "Simply Nature Organic Milk"
    assert first["price"] == 3.99
    assert first["currency"] == "USD"


@respx.mock
async def test_aldi_http_error_returns_empty() -> None:
    respx.get(url__startswith=_KROGER_PRODUCTS_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_WALMART_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_INSTACART_URL).mock(return_value=httpx.Response(500))
    respx.get(url__startswith=_ALDI_URL).mock(return_value=httpx.Response(403))
    assert await grocery.get_grocery_prices("milk", "45202") == []


# ── restaurants ────────────────────────────────────────────────────────


@respx.mock
async def test_restaurant_jsonld_success() -> None:
    respx.get(url__startswith=_DDG_URL).mock(
        return_value=httpx.Response(200, text=_ddg_html(_MENU_URL))
    )
    respx.get(_MENU_URL).mock(return_value=httpx.Response(200, text=_JSONLD_MENU_PAGE))
    result = await restaurants.get_restaurant_menu("Joe's Diner", location="Cincinnati, OH")
    assert result["restaurant"] == "Joe's Diner"
    assert result["location"] == "Cincinnati, OH"
    assert result["source"] == _MENU_URL
    assert len(result["menu"]) == 2
    calamari = result["menu"][0]
    assert calamari["item"] == "Calamari"
    assert calamari["price"] == 11.50
    assert calamari["description"] == "Crispy squid"
    assert calamari["category"] == "Starters"


@respx.mock
async def test_restaurant_html_fallback() -> None:
    respx.get(url__startswith=_DDG_URL).mock(
        return_value=httpx.Response(200, text=_ddg_html(_MENU_URL))
    )
    respx.get(_MENU_URL).mock(return_value=httpx.Response(200, text=_HTML_MENU_PAGE))
    result = await restaurants.get_restaurant_menu("Joe's Diner")
    assert result["restaurant"] == "Joe's Diner"
    assert result["menu"][0] == {
        "item": "Classic Burger",
        "price": 12.99,
        "description": None,
        "category": "Burgers",
    }
    assert any(
        item["item"] == "Milkshake" and item["category"] == "Drinks" for item in result["menu"]
    )


@respx.mock
async def test_restaurant_skips_empty_first_result() -> None:
    respx.get(url__startswith=_DDG_URL).mock(
        return_value=httpx.Response(200, text=_ddg_html(_LANDING_URL, _MENU_URL))
    )
    respx.get(_LANDING_URL).mock(
        return_value=httpx.Response(200, text="<html><body><h1>Home</h1></body></html>")
    )
    respx.get(_MENU_URL).mock(return_value=httpx.Response(200, text=_JSONLD_MENU_PAGE))
    result = await restaurants.get_restaurant_menu("Joe's Diner")
    assert result["source"] == _MENU_URL
    assert len(result["menu"]) == 2


@respx.mock
async def test_restaurant_search_failure_returns_empty() -> None:
    respx.get(url__startswith=_DDG_URL).mock(return_value=httpx.Response(500))
    assert await restaurants.get_restaurant_menu("Joe's Diner") == {}


@respx.mock
async def test_restaurant_no_search_results_returns_empty() -> None:
    respx.get(url__startswith=_DDG_URL).mock(
        return_value=httpx.Response(200, text="<html><body>no results</body></html>")
    )
    assert await restaurants.get_restaurant_menu("Joe's Diner") == {}


@respx.mock
async def test_restaurant_page_fetch_failure_returns_empty() -> None:
    respx.get(url__startswith=_DDG_URL).mock(
        return_value=httpx.Response(200, text=_ddg_html(_MENU_URL))
    )
    respx.get(_MENU_URL).mock(return_value=httpx.Response(503))
    assert await restaurants.get_restaurant_menu("Joe's Diner") == {}


@respx.mock
async def test_restaurant_blank_name_returns_empty() -> None:
    assert await restaurants.get_restaurant_menu("   ") == {}
    assert respx.calls.call_count == 0


# ── router ─────────────────────────────────────────────────────────────


@pytest.fixture
def food_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(food_router)
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_router_grocery_success(food_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, zip_code: str, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "product": "Milk",
                "store": "Kroger",
                "price": 3.49,
                "currency": "USD",
                "zip_code": zip_code,
                "unit": "1 GAL",
                "date": "2026-08-16",
            }
        ]

    monkeypatch.setattr(grocery, "get_grocery_prices", fake)
    resp = _client(food_app).get(
        "/v1/food/grocery", params={"query": "milk", "zip_code": "45202", "limit": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["zip_code"] == "45202"
    assert body["data"][0]["store"] == "Kroger"


def test_router_restaurant_success(food_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(name: str, location: str = "") -> dict[str, Any]:
        return {
            "restaurant": name,
            "location": location,
            "menu": [
                {"item": "Calamari", "price": 11.50, "description": None, "category": "Starters"}
            ],
            "source": "https://example.com/menu",
        }

    monkeypatch.setattr(restaurants, "get_restaurant_menu", fake)
    resp = _client(food_app).get(
        "/v1/food/restaurant/Joe%27s%20Diner", params={"location": "Cincinnati, OH"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["name"] == "Joe's Diner"
    assert body["data"]["menu"][0]["item"] == "Calamari"


def test_router_502_when_module_absent(food_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(food_router_mod, "_food_module", lambda name: None)
    assert (
        _client(food_app)
        .get("/v1/food/grocery", params={"query": "milk", "zip_code": "45202"})
        .status_code
        == 502
    )
    assert _client(food_app).get("/v1/food/restaurant/Joe%27s").status_code == 502


def test_router_validation_422(food_app: FastAPI) -> None:
    assert (
        _client(food_app)
        .get("/v1/food/grocery", params={"query": "milk", "zip_code": "45202", "limit": 0})
        .status_code
        == 422
    )
    assert (
        _client(food_app)
        .get("/v1/food/grocery", params={"query": "milk", "zip_code": "45202", "limit": 101})
        .status_code
        == 422
    )
    assert _client(food_app).get("/v1/food/grocery", params={"query": "milk"}).status_code == 422


def test_router_grocery_blank_query_400(food_app: FastAPI) -> None:
    resp = _client(food_app).get("/v1/food/grocery", params={"query": "   ", "zip_code": "45202"})
    assert resp.status_code == 400
