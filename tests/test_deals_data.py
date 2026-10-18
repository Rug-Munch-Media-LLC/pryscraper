# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the deals_data package (coupons + drop alerts).

Covers the Slickdeals / RetailMeNot structured-data + HTML coupon parsing,
the never-raise contract (network errors, anti-bot blocks, malformed
payloads → [] / {}), the anti-bot ``blocked_sources()`` flagging, the
in-memory + JSON-persisted drop-alert tracker (set/check/list/clear, ASIN
vs keyword price resolution via the guarded marketplace module), and the
/v1/deals/* router (200 + 502-degradation + 422 validation).

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

import json
import sys
import types
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.deals_data.coupons as coupons
import datasets.deals_data.drops as drops
from pry.api.routers.data.deals_data import router as deals_router
from pry.core.errors import PryError


@pytest.fixture(autouse=True)
def _hermetic_deals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill backoff sleeps and reset alert/block state so tests are hermetic."""
    monkeypatch.setattr(coupons, "RETRY_BASE", 0.0)
    monkeypatch.setattr(coupons, "MAX_BACKOFF", 0.0)
    monkeypatch.setattr(coupons, "MAX_RETRIES", 0)
    with coupons._LOCK:
        coupons._BLOCKED.clear()
    drops._reset_alerts()


# ── fixtures ───────────────────────────────────────────────────────────


def _json_ld_html(blocks: list[dict[str, Any]]) -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(block)}</script>' for block in blocks
    )
    return f"<html><head>{scripts}</head><body></body></html>"


def _next_data_html(payload: dict[str, Any]) -> str:
    blob = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    return f"<html><head>{blob}</head><body></body></html>"


def _product_jsonld(title: str, price: float, store: str, url: str) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": title,
        "url": url,
        "brand": {"name": store},
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": "USD",
            "priceValidUntil": "2026-12-31",
        },
    }


def _deal_search_page() -> str:
    """One Slickdeals-ish search page: two JSON-LD Product deals."""
    return _json_ld_html(
        [
            _product_jsonld(
                "Anker 20W USB-C Charger", 12.99, "Amazon", "https://slickdeals.net/f/1"
            ),
            _product_jsonld(
                "Sony WH-1000XM5 Headphones", 249.0, "Best Buy", "https://slickdeals.net/f/2"
            ),
        ]
    )


def _slickdeals_classic_html() -> str:
    """Classic Slickdeals fpGridBox result markup."""
    return """
    <ul class="dealsList">
      <li class="fpGridBox gridItem" data-role="deal-item">
        <a class="itemTitle" href="/f/100-anker">Anker 20W USB-C Charger</a>
        <span class="itemPrice">$12.99</span>
        <span class="itemOldPrice">$19.99</span>
        <span class="itemStore">Amazon</span>
      </li>
      <li class="fpGridBox gridItem" data-role="deal-item">
        <a class="itemTitle" href="/f/101-cable">USB-C Cable 6ft</a>
        <span class="itemPrice">$8.49</span>
        <span class="itemStore">Best Buy</span>
      </li>
    </ul>
    """


def _retailmenot_html() -> str:
    """RetailMeNot merchant-coupon cards."""
    return """
    <div class="coupons">
      <article class="merchant-coupon promo" data-coupon-id="77">
        <a class="merchant-name" href="/view/amazon">Amazon</a>
        <div class="coupon__title">Extra 10% off sitewide</div>
        <div class="coupon__body">Expires 12/31/2026</div>
      </article>
      <article class="merchant-coupon deal" data-coupon-id="78">
        <a class="merchant-name" href="/view/amazon">Amazon</a>
        <div class="coupon__title">$5 off orders over $25</div>
        <div class="coupon__body">Valid through Aug 30, 2026</div>
      </article>
    </div>
    """


_BLOCKED_HTML = (
    "<html><head><title>Attention Required!</title></head>"
    "<body>cf-browser-verification challenge</body></html>"
)


def _deals_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PryError)
    async def pry_error_handler(request: Request, exc: PryError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    app.include_router(deals_router)
    return app


# ── search_deals ───────────────────────────────────────────────────────


@respx.mock
async def test_search_deals_jsonld_success() -> None:
    respx.get(url__startswith="https://slickdeals.net/newsearch.php").mock(
        return_value=httpx.Response(200, text=_deal_search_page())
    )
    respx.get(url__startswith="https://www.retailmenot.com/s/").mock(
        return_value=httpx.Response(200, text=_retailmenot_html())
    )

    results = await coupons.search_deals("charger", limit=10)

    assert len(results) == 4
    slick = [r for r in results if r["source"] == "slickdeals"]
    rmn = [r for r in results if r["source"] == "retailmenot"]
    assert len(slick) == 2
    assert len(rmn) == 2
    first = slick[0]
    expected = {
        "id",
        "title",
        "store",
        "discount",
        "price",
        "original_price",
        "url",
        "expires",
        "source",
    }
    assert set(first) == expected
    assert first["title"] == "Anker 20W USB-C Charger"
    assert first["store"] == "Amazon"
    assert first["price"] == 12.99
    assert first["expires"] == "2026-12-31"
    assert first["url"].startswith("https://slickdeals.net/")
    # no original_price in JSON-LD → discount falls back to None
    assert first["discount"] is None
    assert coupons.blocked_sources() == []


@respx.mock
async def test_search_deals_next_data_embedded_json() -> None:
    payload = {
        "props": {
            "pageProps": {
                "deals": [
                    {
                        "name": "Anker 20W USB-C Charger",
                        "url": "https://slickdeals.net/f/9",
                        "offers": {"price": 11.49},
                        "brand": "Amazon",
                    },
                    {
                        "name": "No Url Deal",
                        "offers": {"price": 1.0},
                    },
                ]
            }
        }
    }
    respx.get(url__startswith="https://slickdeals.net/newsearch.php").mock(
        return_value=httpx.Response(200, text=_next_data_html(payload))
    )
    respx.get(url__startswith="https://www.retailmenot.com/s/").mock(
        return_value=httpx.Response(200, text="")
    )

    results = await coupons.search_deals("anker")

    assert len(results) == 1
    assert results[0]["title"] == "Anker 20W USB-C Charger"
    assert results[0]["price"] == 11.49
    assert results[0]["store"] == "Amazon"


@respx.mock
async def test_search_deals_classic_html_parse() -> None:
    respx.get(url__startswith="https://slickdeals.net/newsearch.php").mock(
        return_value=httpx.Response(200, text=_slickdeals_classic_html())
    )
    respx.get(url__startswith="https://www.retailmenot.com/s/").mock(
        return_value=httpx.Response(200, text="")
    )

    results = await coupons.search_deals("cable")

    assert len(results) == 2
    anker = next(r for r in results if r["title"] == "Anker 20W USB-C Charger")
    assert anker["price"] == 12.99
    assert anker["original_price"] == 19.99
    assert anker["discount"] == 35.0
    assert anker["store"] == "Amazon"
    assert anker["url"] == "https://slickdeals.net/f/100-anker"
    cable = next(r for r in results if r["title"] == "USB-C Cable 6ft")
    assert cable["original_price"] is None
    assert cable["discount"] is None


@respx.mock
async def test_search_deals_retailmenot_coupon_cards() -> None:
    respx.get(url__startswith="https://slickdeals.net/newsearch.php").mock(
        return_value=httpx.Response(200, text="")
    )
    respx.get(url__startswith="https://www.retailmenot.com/s/").mock(
        return_value=httpx.Response(200, text=_retailmenot_html())
    )

    results = await coupons.search_deals("amazon")

    assert len(results) == 2
    pct = next(r for r in results if "10%" in r["title"])
    assert pct["discount"] == 10.0
    assert pct["source"] == "retailmenot"
    five_off = next(r for r in results if "$5 off" in r["title"])
    assert five_off["price"] == 5.0
    assert five_off["expires"] == "Aug 30, 2026"


@respx.mock
async def test_search_deals_antibot_block_returns_empty_and_flags() -> None:
    respx.get(url__startswith="https://slickdeals.net/newsearch.php").mock(
        return_value=httpx.Response(200, text=_BLOCKED_HTML)
    )
    respx.get(url__startswith="https://www.retailmenot.com/s/").mock(
        return_value=httpx.Response(200, text="")
    )

    results = await coupons.search_deals("ps5")

    assert results == []
    expected = ["slickdeals"]
    assert coupons.blocked_sources() == expected


@respx.mock
async def test_search_deals_http_errors_never_raise() -> None:
    respx.get(url__startswith="https://slickdeals.net/newsearch.php").mock(
        return_value=httpx.Response(500)
    )
    # 403 bodies are dropped by _fetch (>= 400), so no block flag is set.
    respx.get(url__startswith="https://www.retailmenot.com/s/").mock(
        return_value=httpx.Response(403, text=_BLOCKED_HTML)
    )

    results = await coupons.search_deals("nintendo")

    assert results == []
    assert coupons.blocked_sources() == []


@respx.mock
async def test_search_deals_network_error_never_raise() -> None:
    respx.get(url__startswith="https://slickdeals.net/newsearch.php").mock(
        side_effect=httpx.ConnectError("boom")
    )
    respx.get(url__startswith="https://www.retailmenot.com/s/").mock(
        side_effect=httpx.ConnectError("boom")
    )

    assert await coupons.search_deals("test") == []
    assert coupons.blocked_sources() == []


@respx.mock
async def test_search_deals_malformed_payloads_never_raise() -> None:
    respx.get(url__startswith="https://slickdeals.net/newsearch.php").mock(
        return_value=httpx.Response(200, text="not json {")
    )
    respx.get(url__startswith="https://www.retailmenot.com/s/").mock(
        return_value=httpx.Response(
            200, text='<html><script type="application/ld+json">{bad}</script></html>'
        )
    )

    assert await coupons.search_deals("test") == []


@respx.mock
async def test_search_deals_empty_query_no_network() -> None:
    assert await coupons.search_deals("   ") == []
    assert await coupons.search_deals("", limit=5) == []
    assert respx.calls.call_count == 0


@respx.mock
async def test_search_deals_dedupes_and_clamps_limit() -> None:
    same_url = _product_jsonld("Same Deal", 5.0, "Amazon", "https://slickdeals.net/f/dupe")
    page = _json_ld_html([same_url, same_url])
    respx.get(url__startswith="https://slickdeals.net/newsearch.php").mock(
        return_value=httpx.Response(200, text=page)
    )
    respx.get(url__startswith="https://www.retailmenot.com/s/").mock(
        return_value=httpx.Response(200, text=_retailmenot_html())
    )

    results = await coupons.search_deals("test", limit=1)

    assert len(results) == 1


# ── get_store_deals ────────────────────────────────────────────────────


@respx.mock
async def test_get_store_deals_success() -> None:
    respx.get(url__startswith="https://slickdeals.net/store/").mock(
        return_value=httpx.Response(200, text=_slickdeals_classic_html())
    )
    respx.get(url__startswith="https://www.retailmenot.com/view/").mock(
        return_value=httpx.Response(200, text=_retailmenot_html())
    )

    results = await coupons.get_store_deals("Amazon", limit=10)

    assert len(results) == 4
    expected = {"slickdeals", "retailmenot"}
    assert {r["source"] for r in results} == expected


@respx.mock
async def test_get_store_deals_empty_store_no_network() -> None:
    assert await coupons.get_store_deals("  ") == []
    assert respx.calls.call_count == 0


# ── drops: set / check / list / clear ──────────────────────────────────


async def test_set_drop_alert_created() -> None:
    result = await drops.set_drop_alert(
        "B0ANAKER20W", target_price=15.0, notify_url="https://hooks/1"
    )
    assert result["status"] == "created"
    assert len(result["alert_id"]) == 12
    alerts = await drops.list_alerts()
    assert len(alerts) == 1
    assert alerts[0]["product"] == "B0ANAKER20W"
    assert alerts[0]["target_price"] == 15.0
    assert alerts[0]["notify_url"] == "https://hooks/1"


async def test_set_drop_alert_blank_product_error() -> None:
    expected = {"alert_id": "", "status": "error"}
    assert await drops.set_drop_alert("   ") == expected


async def test_check_drop_alerts_triggered(monkeypatch: pytest.MonkeyPatch) -> None:
    await drops.set_drop_alert("B0ANAKER20W", target_price=15.0)
    await drops.set_drop_alert("B0CABLE6FT", target_price=10.0)

    async def fake_resolve(product: str) -> float | None:
        return 12.99 if "ANAKER" in product else 24.99

    monkeypatch.setattr(drops, "_resolve_price", fake_resolve)

    results = await drops.check_drop_alerts()

    assert len(results) == 2
    by_product = {r["product"]: r for r in results}
    anker = by_product["B0ANAKER20W"]
    assert anker["current_price"] == 12.99
    assert anker["target_price"] == 15.0
    assert anker["triggered"] is True
    assert anker["delta_pct"] == pytest.approx(-13.4)
    cable = by_product["B0CABLE6FT"]
    assert cable["triggered"] is False
    assert cable["delta_pct"] == pytest.approx(149.9)


async def test_check_drop_alerts_restock_watch_fires_on_any_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await drops.set_drop_alert("Nintendo Switch 2")

    monkeypatch.setattr(drops, "_resolve_price", AsyncMock(return_value=349.99))

    results = await drops.check_drop_alerts()

    assert len(results) == 1
    assert results[0]["target_price"] is None
    assert results[0]["current_price"] == 349.99
    assert results[0]["triggered"] is True
    assert results[0]["delta_pct"] is None


async def test_check_drop_alerts_resolve_failure_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await drops.set_drop_alert("Unavailable Item", target_price=5.0)

    monkeypatch.setattr(drops, "_resolve_price", AsyncMock(return_value=None))

    results = await drops.check_drop_alerts()

    assert len(results) == 1
    assert results[0]["current_price"] is None
    assert results[0]["triggered"] is False
    assert results[0]["delta_pct"] is None


async def test_check_drop_alerts_no_alerts() -> None:
    assert await drops.check_drop_alerts() == []


async def test_clear_alert() -> None:
    created = await drops.set_drop_alert("B0ANAKER20W")
    alert_id = created["alert_id"]
    expected = {"alert_id": alert_id, "status": "cleared"}
    assert await drops.clear_alert(alert_id) == expected
    expected_2 = {"alert_id": alert_id, "status": "not_found"}
    assert await drops.clear_alert(alert_id) == expected_2
    assert await drops.list_alerts() == []


async def test_resolve_price_uses_get_product_for_asin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("fake_amazon")
    fake.get_product = AsyncMock(return_value={"title": "Anker", "price": 12.99})
    fake.search_products = AsyncMock(return_value=[])
    monkeypatch.setitem(sys.modules, "fake_amazon", fake)
    monkeypatch.setattr(drops, "_AMAZON_IMPORT_NAME", "fake_amazon")

    assert await drops._resolve_price("B0ANAKER20") == 12.99
    fake.get_product.assert_awaited_once_with("B0ANAKER20")
    fake.search_products.assert_not_awaited()


async def test_resolve_price_uses_search_for_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("fake_amazon")
    fake.get_product = AsyncMock(return_value={})
    fake.search_products = AsyncMock(return_value=[{"title": "Cable", "price": "8.49"}])
    monkeypatch.setitem(sys.modules, "fake_amazon", fake)
    monkeypatch.setattr(drops, "_AMAZON_IMPORT_NAME", "fake_amazon")

    assert await drops._resolve_price("usb-c cable") == 8.49
    fake.search_products.assert_awaited_once()
    fake.get_product.assert_not_awaited()


async def test_resolve_price_missing_module_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(drops, "_AMAZON_IMPORT_NAME", "no_such_module_xyz")
    assert await drops._resolve_price("B0ANAKER20") is None


async def test_resolve_price_empty_product_none() -> None:
    assert await drops._resolve_price("   ") is None


# ── router ─────────────────────────────────────────────────────────────


def test_router_search_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(query: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": "x", "title": query, "store": "Amazon", "source": "slickdeals"}]

    monkeypatch.setattr(coupons, "search_deals", fake)
    resp = TestClient(_deals_app()).get("/v1/deals/search", params={"query": "ps5"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["title"] == "ps5"
    assert body["limit"] == 20


def test_router_store_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(store: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"id": "y", "title": f"{store} deal", "source": "retailmenot"}]

    monkeypatch.setattr(coupons, "get_store_deals", fake)
    resp = TestClient(_deals_app()).get("/v1/deals/store/amazon")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["title"] == "amazon deal"


def test_router_drops_set_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(
        product: str, target_price: float | None = None, notify_url: str | None = None
    ) -> dict[str, Any]:
        return {"alert_id": "abc123", "status": "created"}

    monkeypatch.setattr(drops, "set_drop_alert", fake)
    resp = TestClient(_deals_app()).get(
        "/v1/deals/drops/set", params={"product": "B0ANAKER20W", "target_price": 15.0}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["alert_id"] == "abc123"


def test_router_drops_check_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake() -> list[dict[str, Any]]:
        return [{"alert_id": "abc123", "product": "X", "triggered": True}]

    monkeypatch.setattr(drops, "check_drop_alerts", fake)
    resp = TestClient(_deals_app()).get("/v1/deals/drops/check")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["data"][0]["triggered"] is True
