"""Walmart marketplace scraper — product detail + search (keyless).
Fetches the public product page (``https://www.walmart.com/ip/{product_id}``)
and search page (``https://www.walmart.com/search?q={query}``) and parses
the ``__NEXT_DATA__`` JSON embedded in the page — a free, no-API approach.
Falls back to Walmart's ``__WML_REDUX_INITIAL_STATE__`` JSON and then to
OpenGraph meta tags when ``__NEXT_DATA__`` is missing.
Contract:

* ``get_product(product_id)`` → ``{product_id,title,price,currency,seller,
  rating,stock,url}`` (``{}`` on failure).
* ``search_products(query, limit=20)`` → list of the same shape (``[]`` on
  failure).

Never raises.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

from pry.commerce.marketplace import (
    _fetch_html,
    _find_redux_state,
    _find_script_json,
    _first_text,
    _lxml_doc,
    _text,
    _to_float,
)

logger = logging.getLogger(__name__)

WALMART_BASE = "https://www.walmart.com"


def _walmart_price(item: dict[str, Any]) -> tuple[float, str]:
    """Walmart price from ``priceInfo`` — API prices are integer cents."""
    price_info = item.get("priceInfo")
    if not isinstance(price_info, dict):
        return 0.0, ""
    for key in ("currentPrice", "unitPrice", "primaryPrice"):
        entry = price_info.get(key)
        if not isinstance(entry, dict):
            continue
        value = entry.get("price")
        if value is None:
            continue
        amount = _to_float(value)
        if amount <= 0:
            continue
        # Walmart's embedded state stores USD prices as integer cents
        # (e.g. 4599 → $45.99). Float prices are already dollars.
        if isinstance(value, int):
            amount = amount / 100.0
        currency = _text(entry.get("currencyUnit") or entry.get("currency"))
        return amount, currency
    return 0.0, ""


def _walmart_stock(item: dict[str, Any]) -> bool:
    """Normalize Walmart availability state into a boolean."""
    status = _text(item.get("availabilityStatus"))
    if status:
        return "IN_STOCK" in status.upper() and "OUT" not in status.upper()
    stock = item.get("stock")
    if isinstance(stock, bool):
        return stock
    if isinstance(stock, str):
        return stock.lower() not in ("out", "out_of_stock", "false", "0", "soldout")
    return False


def _walmart_seller(item: dict[str, Any]) -> str:
    seller = item.get("seller")
    if isinstance(seller, dict):
        return _text(seller.get("displayName") or seller.get("name"))
    return _text(item.get("sellerName"))


def _product_state(data: Any) -> dict[str, Any]:
    """Locate the product object inside __NEXT_DATA__ / redux state."""
    if not isinstance(data, dict):
        return {}
    # __NEXT_DATA__: props.pageProps.initialData.data.product
    try:
        product = data["props"]["pageProps"]["initialData"]["data"].get("product")
    except (KeyError, TypeError):
        logger.warning("walmart_suppressed", exc_info=True)
        product = None
    if isinstance(product, dict) and ("name" in product or "priceInfo" in product):
        return product
    # redux: product.items.byId
    product_root = data.get("product")
    if isinstance(product_root, dict):
        by_id = product_root.get("items", {}).get("byId", {})
        if isinstance(by_id, dict):
            for candidate in by_id.values():
                if isinstance(candidate, dict) and (
                    "name" in candidate or "priceInfo" in candidate
                ):
                    return candidate
    return {}


def _search_items(data: Any) -> list[dict[str, Any]]:
    """Extract the search-result item list from __NEXT_DATA__ / redux state."""
    if not isinstance(data, dict):
        return []
    try:
        search_result = data["props"]["pageProps"]["initialData"]["searchResult"]
    except (KeyError, TypeError):
        logger.warning("walmart_suppressed", exc_info=True)
        search_result = None
    items: list[dict[str, Any]] = []
    for result in (
        search_result,
        data.get("searchResult"),
        (data.get("search") or {}).get("searchResult"),
    ):
        if not isinstance(result, dict):
            continue
        for stack in result.get("itemStacks") or []:
            if not isinstance(stack, dict):
                continue
            for item in stack.get("items") or []:
                if isinstance(item, dict) and item.get("name"):
                    items.append(item)
    return items


def _parse_product_page(html_text: str, product_id: str) -> dict[str, Any]:
    """Parse a Walmart product page into the normalized schema."""
    state = _find_script_json(html_text, "__NEXT_DATA__")
    if state is None:
        state = _find_redux_state(html_text)
    if isinstance(state, dict):
        product = _product_state(state)
        if product:
            price, currency = _walmart_price(product)
            canonical = _text(
                state.get("props", {}).get("pageProps", {}).get("pageInfo", {}).get("canonicalUrl")
            )
            if canonical.startswith("/"):
                canonical = f"{WALMART_BASE}{canonical}"
            return {
                "product_id": _text(product.get("usItemId") or product.get("skuId") or product_id),
                "title": _text(product.get("name")),
                "price": price,
                "currency": currency or "USD",
                "seller": _walmart_seller(product),
                "rating": _to_float(product.get("averageRating")),
                "stock": _walmart_stock(product),
                "url": canonical or f"{WALMART_BASE}/ip/{product_id}",
            }
    # Last resort: OpenGraph meta tags.
    doc = _lxml_doc(html_text)
    if doc is not None:
        title = _first_text(doc.xpath('//meta[@property="og:title"]/@content'))
        if title:
            amount = _to_float(
                _first_text(doc.xpath('//meta[@property="og:price:amount"]/@content'))
            )
            currency = _text(
                _first_text(doc.xpath('//meta[@property="og:price:currency"]/@content'))
            )
            return {
                "product_id": product_id,
                "title": title,
                "price": amount,
                "currency": currency or "USD",
                "seller": "",
                "rating": 0.0,
                "stock": False,
                "url": _first_text(doc.xpath('//meta[@property="og:url"]/@content'))
                or f"{WALMART_BASE}/ip/{product_id}",
            }
    return {}


async def get_product(product_id: str) -> dict[str, Any]:
    """Fetch + normalize one Walmart product; {} on any failure (never raises)."""
    product_id = (product_id or "").strip()
    if not product_id:
        return {}
    url = f"{WALMART_BASE}/ip/{product_id}"
    try:
        html_text = await _fetch_html(url, follow_redirects=True)
        if html_text:
            product = _parse_product_page(html_text, product_id)
            if product.get("title"):
                return product
        return {}
    except Exception as exc:  # noqa: BLE001 - outermost safety net for a never-raise API
        logger.warning(
            "walmart_get_product_failed",
            extra={"product_id": product_id, "error": str(exc)[:160]},
        )
        return {}


def _normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Walmart search-result item into the schema."""
    product_id = _text(item.get("usItemId") or item.get("skuId") or item.get("id"))
    if not product_id:
        return {}
    price, currency = _walmart_price(item)
    url = _text(item.get("canonicalUrl") or item.get("productPageUrl") or item.get("upc"))
    if url.startswith("/"):
        url = f"{WALMART_BASE}{url}"
    if not url or "walmart.com" not in url:
        url = f"{WALMART_BASE}/ip/{product_id}"
    return {
        "product_id": product_id,
        "title": _text(item.get("name")),
        "price": price,
        "currency": currency or "USD",
        "seller": _walmart_seller(item),
        "rating": _to_float(item.get("averageRating")),
        "stock": _walmart_stock(item),
        "url": url,
    }


async def search_products(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search Walmart and return up to ``limit`` normalized products (never raises)."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        cap = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        logger.warning("walmart_suppressed", exc_info=True)
        cap = 20
    try:
        html_text = await _fetch_html(
            f"{WALMART_BASE}/search", params={"q": query}, follow_redirects=True
        )
        if not html_text:
            return []
        state = _find_script_json(html_text, "__NEXT_DATA__")
        if state is None:
            state = _find_redux_state(html_text)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in _search_items(state):
            normalized = _normalize_search_item(item)
            if not normalized or normalized["product_id"] in seen:
                continue
            seen.add(normalized["product_id"])
            results.append(normalized)
            if len(results) >= cap:
                break
        return results
    except Exception as exc:  # noqa: BLE001 - outermost safety net for a never-raise API
        logger.warning(
            "walmart_search_failed",
            extra={"query": query[:80], "error": str(exc)[:160]},
        )
        return []
