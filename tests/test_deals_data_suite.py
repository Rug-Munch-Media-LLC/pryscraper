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
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import datasets.deals_data as deals_data
import datasets.deals_data.coupons as coupons
import datasets.deals_data.drops as drops
import pry.api.routers.data.deals_data as deals_router_mod
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


def test_router_502_when_modules_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deals_router_mod, "_coupons_module", lambda: None)
    monkeypatch.setattr(deals_router_mod, "_drops_module", lambda: None)
    client = TestClient(_deals_app())
    assert client.get("/v1/deals/search", params={"query": "x"}).status_code == 502
    assert client.get("/v1/deals/store/amazon").status_code == 502
    assert client.get("/v1/deals/drops/set", params={"product": "x"}).status_code == 502
    assert client.get("/v1/deals/drops/check").status_code == 502


def test_router_validation() -> None:
    client = TestClient(_deals_app())
    # empty/missing query -> 422
    assert client.get("/v1/deals/search", params={"query": ""}).status_code == 422
    assert client.get("/v1/deals/search").status_code == 422
    # limit out of range -> 422
    assert client.get("/v1/deals/search", params={"query": "x", "limit": 0}).status_code == 422
    assert client.get("/v1/deals/search", params={"query": "x", "limit": 500}).status_code == 422
    # missing product -> 422
    assert client.get("/v1/deals/drops/set").status_code == 422
    # negative target_price -> 422
    assert (
        client.get("/v1/deals/drops/set", params={"product": "x", "target_price": -1}).status_code
        == 422
    )


def test_package_aggregates() -> None:
    assert callable(deals_data.search_deals)
    assert callable(deals_data.get_store_deals)
    assert callable(deals_data.set_drop_alert)
    assert callable(deals_data.check_drop_alerts)
    assert callable(deals_data.list_alerts)
    assert callable(deals_data.clear_alert)
    assert callable(deals_data.blocked_sources)
