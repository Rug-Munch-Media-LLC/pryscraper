"""TikTok Shop marketplace scraper — product detail + trending (keyless).
Fetches the unauthenticated web render endpoint
(``https://www.tiktok.com/shop/pdp/render/{product_id}`` — the JSON the
TikTok Shop web app itself uses, no API key) with an OpenGraph-meta
fallback on the product page, then normalizes into the marketplace schema.
``get_trending`` attempts the category bestseller page; TikTok Shop's
bestseller surfaces are JS-rendered and require signed requests, so when
the scrape yields nothing it returns ``[]`` (or clearly-marked placeholder
rows when ``PRY_TIKTOK_TRENDING_PLACEHOLDER=1``). See [REVIEW] notes in
the module docstring below.

Contract:

* ``get_product(product_id)`` → ``{product_id,title,price,sold_count,
  gmv_estimate,rating,shop,url}`` (``{}`` on failure).
* ``get_trending(limit=50)`` → list of the same shape (``[]`` on failure).

``gmv_estimate`` is delta-based: the first observation seeds a snapshot of
``sold_count`` and reports ``sold_count * price``; subsequent observations
with a higher sold count report ``(sold_count - previous) * price`` for the
incremental GMV since the last poll.

Never raises.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
import time
from typing import Any

from pry.commerce.marketplace import (
    _fetch_html,
    _fetch_json,
    _first_text,
    _lxml_doc,
    _text,
    _to_float,
    _to_int,
)

logger = logging.getLogger(__name__)

TIKTOK_BASE = "https://www.tiktok.com/shop"


# ── GMV estimation (delta-based on sold-count snapshots) ───────────────
_gmv_snapshots: dict[str, tuple[float, int]] = {}


def _reset_gmv_snapshots() -> None:
    """Clear the sold-count snapshot store (used by tests)."""
    _gmv_snapshots.clear()


def _estimate_gmv(product_id: str, sold_count: int, price: float) -> float:
    """Delta-based GMV estimate; 0.0 when sold count or price is unknown."""
    if sold_count <= 0 or price <= 0:
        return 0.0
    now = time.monotonic()
    previous = _gmv_snapshots.get(product_id)
    if previous is None:
        _gmv_snapshots[product_id] = (now, sold_count)
        return round(float(sold_count) * price, 2)
    _, previous_sold = previous
    delta = sold_count - previous_sold
    _gmv_snapshots[product_id] = (now, sold_count)
    if delta > 0:
        return round(float(delta) * price, 2)
    return round(float(sold_count) * price, 2)


# ── Parsing helpers ────────────────────────────────────────────────────


def _tiktok_price(value: Any) -> tuple[float, str]:
    """Price from the render payload (int cents, dict, or string)."""
    if isinstance(value, dict):
        raw = value.get("value") or value.get("amount") or value.get("price")
        currency = _text(value.get("currency") or value.get("currencyCode"))
        return _tiktok_price(raw)[0], currency or _tiktok_price(raw)[1]
    if isinstance(value, (int, float)):
        amount = _to_float(value)
        if isinstance(value, int) and amount >= 100:
            amount = amount / 100.0  # render API prices are integer cents
        return amount, ""
    amount, currency = 0.0, ""
    # String form: "$12.34" or "12.34" or "CN¥ 88.00"
    for token in _text(value).split():
        if token.startswith(("$", "€", "£", "¥", "C$", "A$")):
            currency = {
                "$": "USD",
                "€": "EUR",
                "£": "GBP",
                "¥": "CNY",
                "C$": "CAD",
                "A$": "AUD",
            }.get(token[0], "")
            continue
        try:
            amount = float(token.replace(",", ""))
        except ValueError:
            logger.warning("tiktok_shop_suppressed", exc_info=True)
            continue
    return amount, currency


def _tiktok_rating(value: Any) -> float:
    if isinstance(value, dict):
        return _to_float(value.get("value") or value.get("score") or value.get("rating"))
    return _to_float(value)


def _tiktok_sold_count(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("value") or value.get("count") or value.get("sold")
    return _to_int(value)


def _tiktok_shop_name(product_info: dict[str, Any]) -> str:
    shop = product_info.get("shop")
    if isinstance(shop, dict):
        return _text(shop.get("name") or shop.get("shopName") or shop.get("title"))
    return _text(product_info.get("shopName") or product_info.get("sellerName"))


def _from_render_json(data: Any, product_id: str) -> dict[str, Any]:
    """Normalize the pdp/render JSON payload into the schema."""
    if not isinstance(data, dict):
        return {}
    payload = data.get("data")
    if not isinstance(payload, dict):
        return {}
    product_info = payload.get("productInfo")
    if not isinstance(product_info, dict):
        product_info = payload.get("product")
    if not isinstance(product_info, dict) or not product_info.get("title"):
        return {}
    price, _ = _tiktok_price(product_info.get("price"))
    sold_count = _tiktok_sold_count(
        product_info.get("soldCount") or product_info.get("sales") or product_info.get("salesCount")
    )
    gmv = _estimate_gmv(product_id, sold_count, price)
    return {
        "product_id": product_id,
        "title": _text(product_info.get("title") or product_info.get("productTitle")),
        "price": price,
        "sold_count": sold_count,
        "gmv_estimate": gmv,
        "rating": _tiktok_rating(product_info.get("rating") or product_info.get("ratingValue")),
        "shop": _tiktok_shop_name(product_info),
        "url": f"{TIKTOK_BASE}/pdp/{product_id}",
    }


def _from_og_meta(html_text: str, product_id: str) -> dict[str, Any]:
    """Fallback: parse OpenGraph meta tags from the PDP HTML page."""
    doc = _lxml_doc(html_text)
    if doc is None:
        return {}
    title = _first_text(doc.xpath('//meta[@property="og:title"]/@content'))
    if not title:
        return {}
    amount = _to_float(_first_text(doc.xpath('//meta[@property="og:price:amount"]/@content')))
    sold_raw = _first_text(doc.xpath('//meta[@property="product:sale_count"]/@content'))
    sold_count = _to_int(sold_raw)
    return {
        "product_id": product_id,
        "title": title,
        "price": amount,
        "sold_count": sold_count,
        "gmv_estimate": _estimate_gmv(product_id, sold_count, amount),
        "rating": 0.0,
        "shop": "",
        "url": f"{TIKTOK_BASE}/pdp/{product_id}",
    }


async def get_product(product_id: str) -> dict[str, Any]:
    """Fetch + normalize one TikTok Shop product; {} on any failure (never raises)."""
    product_id = (product_id or "").strip()
    if not product_id:
        return {}
    try:
        # 1) Preferred: the unauthenticated render JSON the web app uses.
        data = await _fetch_json(f"{TIKTOK_BASE}/pdp/render/{product_id}")
        product = _from_render_json(data, product_id)
        if product:
            return product
        # 2) Fallback: OpenGraph meta on the PDP HTML page.
        html_text = await _fetch_html(f"{TIKTOK_BASE}/pdp/{product_id}")
        if html_text:
            product = _from_og_meta(html_text, product_id)
            if product:
                return product
        return {}
    except Exception as exc:  # noqa: BLE001 - outermost safety net for a never-raise API
        logger.warning(
            "tiktok_get_product_failed",
            extra={"product_id": product_id, "error": str(exc)[:160]},
        )
        return {}


def _placeholder_trending(limit: int) -> list[dict[str, Any]]:
    """Clearly-marked placeholder rows so downstream consumers see the shape.

    Only used when ``PRY_TIKTOK_TRENDING_PLACEHOLDER=1`` — the default
    contract is ``[]`` on failure.
    """
    return [
        {
            "product_id": "",
            "title": "[placeholder] TikTok Shop trending — page not scrapeable",
            "price": 0.0,
            "sold_count": 0,
            "gmv_estimate": 0.0,
            "rating": 0.0,
            "shop": "",
            "url": "",
        }
    ]


async def get_trending(limit: int = 50) -> list[dict[str, Any]]:
    """Return up to ``limit`` TikTok Shop trending products (never raises).

    [REVIEW] Feasibility: TikTok Shop's bestseller/category surfaces are
    JS-rendered and require signed requests (their web app calls the
    ``/api/shop/...`` endpoints with server-issued signatures). The plain
    ``pdp/render`` endpoint only serves individual product ids, so there is
    no reliable server-side entry point for "trending" without a browser
    (Playwright) or an official API key. This function attempts the
    bestseller page once and, on failure, returns ``[]`` (or clearly-marked
    placeholder rows when ``PRY_TIKTOK_TRENDING_PLACEHOLDER=1``). The
    recommended upgrade path is wiring TikTok Shop's official Product Search
    / affiliate API behind an env-provided key.
    """
    try:
        cap = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        logger.warning("tiktok_shop_suppressed", exc_info=True)
        cap = 50
    try:
        # Best-effort: the bestseller JSON surface used by some regions.
        data = await _fetch_json(
            f"{TIKTOK_BASE}/v2/best_sellers",
            params={"limit": str(cap)},
            retries=1,
        )
        items = (
            data.get("data") or data.get("items") or (data.get("data") or {}).get("items")
            if isinstance(data, dict)
            else None
        )
        if isinstance(items, list):
            results: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                product_id = _text(
                    item.get("product_id") or item.get("id") or item.get("productId")
                )
                if not product_id:
                    continue
                price, _ = _tiktok_price(item.get("price"))
                sold_count = _tiktok_sold_count(item.get("soldCount") or item.get("sales"))
                results.append(
                    {
                        "product_id": product_id,
                        "title": _text(item.get("title") or item.get("name")),
                        "price": price,
                        "sold_count": sold_count,
                        "gmv_estimate": _estimate_gmv(product_id, sold_count, price),
                        "rating": _tiktok_rating(item.get("rating")),
                        "shop": _text(item.get("shopName") or (item.get("shop") or {}).get("name")),
                        "url": f"{TIKTOK_BASE}/pdp/{product_id}",
                    }
                )
                if len(results) >= cap:
                    break
            return results
        if os.getenv("PRY_TIKTOK_TRENDING_PLACEHOLDER", "0").lower() in ("1", "true", "yes", "on"):
            return _placeholder_trending(cap)
        return []
    except Exception as exc:  # noqa: BLE001 - outermost safety net for a never-raise API
        logger.warning(
            "tiktok_trending_failed",
            extra={"error": str(exc)[:160]},
        )
        if os.getenv("PRY_TIKTOK_TRENDING_PLACEHOLDER", "0").lower() in ("1", "true", "yes", "on"):
            return _placeholder_trending(cap)
        return []
