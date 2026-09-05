"""Embedded-JSON extraction and normalization for retail marketplace pages.

Layered parse: JSON-LD ``Product`` / ``ItemList`` first, then the Next.js
``__NEXT_DATA__`` state and the ``window.__INITIAL_STATE__`` /
``__PRELOADED_STATE__`` / ``__APOLLO_STATE__`` redux blobs, then
OpenGraph meta tags as a last resort.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from pry.commerce.marketplace import (
    _find_script_json,
    _first_text,
    _lxml_doc,
    _text,
    _to_float,
)
from pry.commerce.marketplace._retail_stores import _STORES, _absolute, _product_url

if TYPE_CHECKING:
    from collections.abc import Iterator

# ── Shared small helpers ───────────────────────────────────────────────

_MONEY_RE = re.compile(r"\d[\d.,]*")
_WINDOW_STATE_MARKERS = (
    "__NEXT_DATA__",
    "__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "__APOLLO_STATE__",
)
_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

# Keys considered "product id"-ish inside embedded state (plain ``id`` is
# too common — breadcrumbs / facets carry it — so it is not accepted).
_PRODUCT_ID_KEYS = (
    "tcin",
    "sku",
    "productId",
    "itemId",
    "product_id",
    "dpci",
    "productCode",
    "itemNumber",
)
_PRICE_KEYS = (
    "price",
    "currentPrice",
    "offerPrice",
    "salePrice",
    "listPrice",
    "regularPrice",
    "formattedPrice",
)
_CURRENCY_MAP = {"$": "USD", "€": "EUR", "£": "GBP"}


def _walk_dicts(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict (at any depth) inside a parsed JSON tree."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _price_value(value: Any) -> float | None:
    """Coerce one price value to float: plain number, money string, or
    ``{"amount": .., "divisor": ..}`` (integer cents) dict."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        amount = value.get("amount")
        divisor = value.get("divisor")
        if isinstance(amount, (int, float)) and isinstance(divisor, (int, float)) and divisor:
            return float(amount) / float(divisor)
        for key in ("price", "value", "currentPrice"):
            if key in value:
                return _price_value(value[key])
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = _MONEY_RE.search(value)
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", ""))
        except ValueError:
            return None
    return None


def _first_price(d: dict[str, Any]) -> float | None:
    """Best-effort price extraction from a product-like dict."""
    for key in _PRICE_KEYS:
        if key in d:
            parsed = _price_value(d[key])
            if parsed is not None:
                return parsed
    price_info = d.get("priceInfo")  # Walmart-style nested price object
    if isinstance(price_info, dict):
        for entry in price_info.values():
            if not isinstance(entry, dict):
                continue
            for sub in ("price", "currentPrice"):
                parsed = _price_value(entry.get(sub))
                if parsed is not None:
                    return parsed
    return None


def _has_price_signal(d: dict[str, Any]) -> bool:
    """True when the dict carries a plausible price field (any type)."""
    for key in _PRICE_KEYS:
        if key not in d:
            continue
        value = d[key]
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, dict):
            if any(sub in value for sub in ("amount", "price", "value", "currentPrice")):
                return True
            continue
        return True
    return bool(isinstance(d.get("priceInfo"), dict))


def _product_id_value(d: dict[str, Any]) -> str:
    """First product-ish id found on the dict; "" when absent."""
    for key in _PRODUCT_ID_KEYS:
        value = d.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, str)):
            cleaned = _text(value)
            if cleaned:
                return cleaned
    return ""


def _looks_like_product(d: dict[str, Any]) -> bool:
    """Heuristic: title + (price signal or product id) ⇒ product record."""
    title = _text(d.get("title") or d.get("name") or d.get("productName") or d.get("product_title"))
    if len(title) < 2:
        return False
    return _has_price_signal(d) or bool(_product_id_value(d))


def _currency_from(d: dict[str, Any]) -> str | None:
    for key in ("currencyCode", "currency_code", "currency"):
        value = d.get(key)
        if isinstance(value, str) and value.strip():
            code = value.strip()
            if code in _CURRENCY_MAP:
                return _CURRENCY_MAP[code]
            if len(code) == 3 and code.isalpha():
                return code.upper()
    return None


def _rating_from(d: dict[str, Any]) -> float | None:
    for key in ("rating", "averageRating", "customerReviewAverage", "reviewAverage"):
        if key in d:
            value = _to_float(d[key])
            if value:
                return value
    aggregate = d.get("aggregateRating")
    if isinstance(aggregate, dict):
        value = _to_float(aggregate.get("ratingValue"))
        if value:
            return value
    return None


def _stock_from(d: dict[str, Any]) -> bool:
    """Normalize availability signals into a boolean (default False)."""
    for key in ("availability", "availabilityStatus", "inStock", "stock", "isInStock"):
        if key not in d:
            continue
        value = d[key]
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            low = value.lower()
            if "outofstock" in low.replace(" ", "") or low in (
                "out",
                "soldout",
                "out_of_stock",
                "false",
                "0",
            ):
                return False
            if "instock" in low.replace(" ", "") or low in ("in_stock", "true", "1", "in stock"):
                return True
    return False


def _seller_from(d: dict[str, Any]) -> str | None:
    for key in ("seller", "sellerName", "brand", "brandName", "storeName"):
        value = d.get(key)
        if isinstance(value, dict):
            name = _text(value.get("name") or value.get("displayName"))
            if name:
                return name
        else:
            name = _text(value)
            if name:
                return name
    return None


# ── Embedded JSON extraction ───────────────────────────────────────────


def _extract_window_state(html_text: str, marker: str) -> Any:
    """Parse ``window.<marker> = {...};`` JSON via brace counting; None on failure."""
    if not html_text:
        return None
    idx = html_text.find(f"window.{marker}")
    if idx < 0:
        return None
    start = html_text.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(html_text)):
        ch = html_text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(html_text[start : i + 1])
                    return data if isinstance(data, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _embedded_state(html_text: str) -> Any:
    """Return the first parseable embedded state blob (dict) or None."""
    state = _find_script_json(html_text, "__NEXT_DATA__")
    if state is not None:
        return state
    for marker in _WINDOW_STATE_MARKERS:
        state = _extract_window_state(html_text, marker)
        if state is not None:
            return state
    return None


def _json_ld_objects(html_text: str) -> list[Any]:
    """Every JSON-LD object embedded in the page (never raises)."""
    out: list[Any] = []
    for match in _LD_RE.finditer(html_text or ""):
        try:
            data = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(data)
        elif isinstance(data, dict):
            out.append(data)
    return out


def _ld_type(obj: Any) -> str:
    if isinstance(obj, dict):
        value = obj.get("@type")
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value or "")
    return ""


def _find_ld_product(html_text: str) -> dict[str, Any] | None:
    for obj in _json_ld_objects(html_text):
        if "Product" in _ld_type(obj):
            return obj if isinstance(obj, dict) else None
    return None


def _find_ld_search_items(html_text: str) -> list[dict[str, Any]]:
    """JSON-LD search candidates: ItemList entries and bare Product objects."""
    items: list[dict[str, Any]] = []
    for obj in _json_ld_objects(html_text):
        obj_type = _ld_type(obj)
        if "ItemList" in obj_type:
            elements = obj.get("itemListElement")
            if isinstance(elements, list):
                for element in elements:
                    if not isinstance(element, dict):
                        continue
                    item = element.get("item")
                    if isinstance(item, dict):
                        items.append(item)
                    else:
                        items.append(element)
        elif "Product" in obj_type and isinstance(obj, dict):
            items.append(obj)
    return items


# ── Normalization ──────────────────────────────────────────────────────


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
