"""Shared helpers and normalization for retail marketplace parsing.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pry.commerce.marketplace import _text, _to_float

if TYPE_CHECKING:
    from collections.abc import Iterator

# ── Shared small helpers ───────────────────────────────────────────────

_MONEY_RE = re.compile(r"\d[\d.,]*")

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
