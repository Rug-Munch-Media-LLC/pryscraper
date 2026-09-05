"""Record normalization and layered parsing for retail marketplace pages.

Maps extracted JSON-LD / embedded-state / OpenGraph data onto the canonical
product record schema, with layered fallback: JSON-LD → embedded state →
OG meta tags.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from typing import Any

from pry.commerce.marketplace import (
    _first_text,
    _lxml_doc,
    _text,
    _to_float,
)
from pry.commerce.marketplace._retail_common import (
    _currency_from,
    _first_price,
    _looks_like_product,
    _price_value,
    _product_id_value,
    _rating_from,
    _seller_from,
    _stock_from,
    _walk_dicts,
)
from pry.commerce.marketplace._retail_extract import (
    _embedded_state,
    _find_ld_product,
    _find_ld_search_items,
)
from pry.commerce.marketplace._retail_stores import _STORES, _absolute, _product_url


def _ld_product_record(
    store_key: str,
    obj: dict[str, Any],
    fallback_url: str = "",
    fallback_id: str = "",
) -> dict[str, Any] | None:
    """Map a JSON-LD Product (or ItemList entry) onto the canonical record."""
    title = _text(obj.get("name") or obj.get("title"))
    if not title:
        return None
    offers = obj.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    price: float | None = None
    currency: str | None = None
    stock = False
    if isinstance(offers, dict):
        price = _price_value(
            offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
        )
        cur = offers.get("priceCurrency") or offers.get("currency")
        if isinstance(cur, str) and len(cur) == 3 and cur.isalpha():
            currency = cur.upper()
        stock = _stock_from({"availability": offers.get("availability")})
    product_id = (
        _text(obj.get("sku") or obj.get("productID") or obj.get("mpn") or obj.get("gtin13"))
        or fallback_id
    )
    url = _absolute(store_key, obj.get("url") or obj.get("@id"))
    if not url and product_id:
        url = _product_url(_STORES[store_key], product_id)
    if not url:
        url = fallback_url
    return {
        "store": store_key,
        "product_id": product_id,
        "title": title,
        "price": price,
        "currency": currency or _currency_from(obj),
        "seller": _seller_from(obj),
        "rating": _rating_from(obj),
        "stock": stock,
        "url": url,
        "confidence": _STORES[store_key]["confidence"],
    }


def _state_product_record(
    store_key: str, d: dict[str, Any], fallback_url: str = ""
) -> dict[str, Any] | None:
    """Map a product-like dict found inside embedded state onto the schema."""
    title = _text(d.get("title") or d.get("name") or d.get("productName") or d.get("product_title"))
    if len(title) < 2:
        return None
    product_id = _product_id_value(d)
    price = _first_price(d)
    url = _absolute(
        store_key,
        d.get("url") or d.get("productUrl") or d.get("product_url") or d.get("canonicalUrl"),
    )
    if not url and product_id:
        url = _product_url(_STORES[store_key], product_id)
    if not url:
        url = fallback_url
    return {
        "store": store_key,
        "product_id": product_id,
        "title": title,
        "price": price,
        "currency": _currency_from(d),
        "seller": _seller_from(d),
        "rating": _rating_from(d),
        "stock": _stock_from(d),
        "url": url,
        "confidence": _STORES[store_key]["confidence"],
    }


def _walk_product_record(
    store_key: str, state: Any, fallback_url: str = "", fallback_id: str = ""
) -> dict[str, Any] | None:
    """First product-like record deep inside embedded state; None if absent."""
    for d in _walk_dicts(state):
        if not isinstance(d, dict) or not _looks_like_product(d):
            continue
        record = _state_product_record(store_key, d, fallback_url)
        if record and record["title"]:
            if not record["product_id"] and fallback_id:
                record["product_id"] = fallback_id
            return record
    return None


def _walk_search_records(store_key: str, state: Any, limit: int) -> list[dict[str, Any]]:
    """Product-like records deep inside embedded search state, deduped."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in _walk_dicts(state):
        if not isinstance(d, dict) or not _looks_like_product(d):
            continue
        record = _state_product_record(store_key, d)
        if not record or not record["title"]:
            continue
        key = record["product_id"] or f"{record['title']}|{record['price']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
        if len(out) >= limit:
            break
    return out


def _og_record(
    store_key: str, html_text: str, product_id: str, fallback_url: str
) -> dict[str, Any] | None:
    """Last-resort OpenGraph meta extraction (low confidence)."""
    doc = _lxml_doc(html_text)
    if doc is None:
        return None
    title = _first_text(doc.xpath('//meta[@property="og:title"]/@content'))
    if not title:
        return None
    amount = _to_float(_first_text(doc.xpath('//meta[@property="og:price:amount"]/@content')))
    currency = _text(_first_text(doc.xpath('//meta[@property="og:price:currency"]/@content')))
    url = _first_text(doc.xpath('//meta[@property="og:url"]/@content')) or fallback_url
    return {
        "store": store_key,
        "product_id": product_id,
        "title": title,
        "price": amount if amount else None,
        "currency": currency or None,
        "seller": None,
        "rating": None,
        "stock": False,
        "url": url,
        "confidence": "low",
    }


def _parse_product_page(
    store_key: str, html_text: str, product_id: str, url: str
) -> dict[str, Any] | None:
    """Layered parse of a product page: JSON-LD → embedded state → OG meta."""
    ld = _find_ld_product(html_text)
    if ld:
        record = _ld_product_record(store_key, ld, fallback_url=url, fallback_id=product_id)
        if record:
            return record
    state = _embedded_state(html_text)
    if state is not None:
        record = _walk_product_record(store_key, state, fallback_url=url, fallback_id=product_id)
        if record:
            return record
    return _og_record(store_key, html_text, product_id, url)


def _parse_search_page(store_key: str, html_text: str, limit: int) -> list[dict[str, Any]]:
    """Layered parse of a search page: JSON-LD ItemList → embedded state."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for obj in _find_ld_search_items(html_text):
        record = _ld_product_record(store_key, obj, fallback_id=_text(obj.get("sku")))
        if not record or not record["title"]:
            continue
        key = record["product_id"] or f"{record['title']}|{record['price']}"
        if key in seen:
            continue
        seen.add(key)
        results.append(record)
        if len(results) >= limit:
            return results
    state = _embedded_state(html_text)
    if state is not None:
        for record in _walk_search_records(store_key, state, limit):
            key = record["product_id"] or f"{record['title']}|{record['price']}"
            if key in seen:
                continue
            seen.add(key)
            results.append(record)
            if len(results) >= limit:
                break
    return results
