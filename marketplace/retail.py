"""Retail marketplace scrapers — Target, Best Buy, Costco, Home Depot, Lowe's, Macy's, Kohl's, Staples.

Keyless, free-tier product search + lookup for the big US general
retailers, mirroring the ``marketplace.amazon`` / ``marketplace.walmart``
approach: fetch the public product / search page and parse whatever the
server embeds — JSON-LD ``Product`` / ``ItemList`` first, then the
Next.js ``__NEXT_DATA__`` state and the ``window.__INITIAL_STATE__`` /
``__PRELOADED_STATE__`` / ``__APOLLO_STATE__`` redux blobs, then
OpenGraph meta tags as a last resort. No API keys anywhere.

Transport reuses the package's httpx + stealth-user-agent helpers and
optionally routes through a Webshare residential proxy
(``WEBSHARE_PROXY_LIST`` env var / gopass, see :mod:`webshare_proxy`)
to satisfy geo-gated retailers (Costco needs a US IP) and to dodge
anti-bot challenges from datacenter IPs.

Contract:

* ``search_retail(query, store="all", limit=20)`` — async, never raises,
  returns ``list[dict]`` (``[]`` on any failure / empty query / unknown
  store). ``store`` is one of the registry keys below (aliases accepted:
  ``"best buy"``, ``"lowe's"``, ``"home depot"``, ``"macy's"``,
  ``"kohl's"``) or ``"all"`` to aggregate every store (per-store
  degradation, deduplicated, capped at ``limit``).
* ``get_retail_product(store, product_id)`` — async, never raises,
  returns ``dict`` (``{}`` on any failure).

Canonical record shape::

    {
        "store": "target",            # registry key
        "product_id": str,            # store-specific id (tcin, sku, itemId…)
        "title": str,
        "price": float | None,
        "currency": str | None,       # ISO-4217 code
        "seller": str | None,         # brand / seller name when available
        "rating": float | None,
        "stock": bool,
        "url": str,
        "confidence": "medium",       # per-store reliability (see registry)
    }

Store registry (confidence = how reliably the embedded JSON is present
and parseable from a plain HTTP GET; ``js_gated`` = known to serve
anti-bot / JS challenges to datacenter IPs):

====================  =============  =========  ================================
store key             confidence     js_gated   extraction method
====================  =============  =========  ================================
target                medium         no         JSON-LD Product + __NEXT_DATA__
bestbuy               medium         yes        JSON-LD Product + __NEXT_DATA__ (Akamai)
costco                medium         yes        JSON-LD Product (Cloudflare, geo US)
homedepot             low            yes        JSON-LD + __APOLLO_STATE__ (aggressive Akamai)
lowes                 medium         no         JSON-LD + __INITIAL_STATE__
macys                 low            yes        JSON-LD + __PRELOADED_STATE__ (PerimeterX)
kohls                 medium         no         JSON-LD Product
staples               medium         no         JSON-LD Product
====================  =============  =========  ================================

Reliably scrapeable today (JSON-LD is server-rendered, no JS required):
**Target**, **Lowe's**, **Kohl's**, **Staples**. JS-gated (frequently
serve challenges / login walls to non-browser clients, proxy helps):
**Best Buy**, **Costco**, **Home Depot**, **Macy's**. All of them
degrade to ``[]`` / ``{}`` silently when blocked or layout changes —
never an exception.

Never raises: every public function wraps transport/parse failures and
returns the degraded empty value. Optional API keys are never required.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from marketplace import (
    _find_script_json,
    _first_text,
    _http_retries,
    _lxml_doc,
    _rotate_ua,
    _text,
    _to_float,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# ── Store registry ─────────────────────────────────────────────────────

_STORES: dict[str, dict[str, Any]] = {
    "target": {
        "name": "Target",
        "host": "www.target.com",
        "search_url": "https://www.target.com/s?searchTerm={q}",
        "product_url": "https://www.target.com/p/{product_id}",
        "confidence": "medium",
        "js_gated": False,
        "notes": "Server-rendered JSON-LD Product + __NEXT_DATA__; occasionally serves bot walls on datacenter IPs.",
    },
    "bestbuy": {
        "name": "Best Buy",
        "host": "www.bestbuy.com",
        "search_url": "https://www.bestbuy.com/site/searchpage.jsp?st={q}",
        "product_url": "https://www.bestbuy.com/site/{product_id}",
        "confidence": "medium",
        "js_gated": True,
        "notes": "JSON-LD Product + __NEXT_DATA__; Akamai bot manager frequently challenges datacenter IPs (proxy helps).",
    },
    "costco": {
        "name": "Costco",
        "host": "www.costco.com",
        "search_url": "https://www.costco.com/CatalogSearch?keyword={q}",
        "product_url": "https://www.costco.com/{product_id}.html",
        "confidence": "medium",
        "js_gated": True,
        "notes": "JSON-LD Product present; Cloudflare + geo-gated (needs a US IP via the Webshare proxy).",
    },
    "homedepot": {
        "name": "Home Depot",
        "host": "www.homedepot.com",
        "search_url": "https://www.homedepot.com/s/{q}",
        "product_url": "https://www.homedepot.com/p/{product_id}",
        "confidence": "low",
        "js_gated": True,
        "notes": "JSON-LD + __APOLLO_STATE__; aggressive Akamai bot protection, frequently JS-gated.",
    },
    "lowes": {
        "name": "Lowe's",
        "host": "www.lowes.com",
        "search_url": "https://www.lowes.com/search?searchTerm={q}",
        "product_url": "https://www.lowes.com/pd/{product_id}",
        "confidence": "medium",
        "js_gated": False,
        "notes": "JSON-LD + __INITIAL_STATE__; some bot protection, generally scrapeable.",
    },
    "macys": {
        "name": "Macy's",
        "host": "www.macys.com",
        "search_url": "https://www.macys.com/shop/search?keyword={q}",
        "product_url": "https://www.macys.com/shop/product/{product_id}",
        "confidence": "low",
        "js_gated": True,
        "notes": "JSON-LD + __PRELOADED_STATE__; PerimeterX anti-bot often blocks datacenter traffic.",
    },
    "kohls": {
        "name": "Kohl's",
        "host": "www.kohls.com",
        "search_url": "https://www.kohls.com/search.jsp?search={q}",
        "product_url": "https://www.kohls.com/product/prd-{product_id}",
        "confidence": "medium",
        "js_gated": False,
        "notes": "JSON-LD Product on product pages; moderate bot protection.",
    },
    "staples": {
        "name": "Staples",
        "host": "www.staples.com",
        "search_url": "https://www.staples.com/search?query={q}",
        "product_url": "https://www.staples.com/{product_id}.html",
        "confidence": "medium",
        "js_gated": False,
        "notes": "JSON-LD Product; moderate bot protection, generally scrapeable.",
    },
}

# Normalized (lowercase, alnum-only) store aliases → registry key.
_STORE_ALIASES: dict[str, str] = {
    "target": "target",
    "bestbuy": "bestbuy",
    "costco": "costco",
    "homedepot": "homedepot",
    "lowes": "lowes",
    "macys": "macys",
    "kohls": "kohls",
    "staples": "staples",
}

# ── HTTP configuration ─────────────────────────────────────────────────

HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
RETRY_BASE = 0.5  # seconds — exponential backoff base
MAX_BACKOFF = 3.0  # seconds — backoff cap
_MAX_LIMIT = 100

_BASE_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

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


def _clamp_limit(limit: Any) -> int:
    """Coerce ``limit`` to an int within [1, _MAX_LIMIT]; default 20."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, _MAX_LIMIT))


def _url_quote(query: str) -> str:
    return quote(query, safe="")


def _normalize_store(store: str) -> str:
    """Normalize a store name/alias to a registry key; "" when unknown."""
    key = re.sub(r"[^a-z]", "", (store or "").lower())
    return _STORE_ALIASES.get(key, "")


def _product_url(info: dict[str, Any], product_id: str) -> str:
    return info["product_url"].format(product_id=quote(product_id, safe="/"))


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


def _absolute(store_key: str, value: Any) -> str:
    """Turn a relative product URL into an absolute one for the store host."""
    text = _text(value)
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith("/"):
        return f"https://{_STORES[store_key]['host']}{text}"
    return text


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


# ── Transport ──────────────────────────────────────────────────────────


def _next_proxy() -> str | None:
    """Next Webshare residential proxy (``WEBSHARE_PROXY_LIST``), or None."""
    try:
        from webshare_proxy import next_webshare_proxy

        return next_webshare_proxy()
    except Exception:  # noqa: BLE001 - proxy pool is best-effort
        return None


def _backoff(attempt: int) -> float:
    """Exponential backoff with cap."""
    return min(RETRY_BASE * (2**attempt), MAX_BACKOFF)


async def _fetch_page(url: str) -> str | None:
    """GET a retail page (stealth UA + optional Webshare proxy); None on failure.

    Never raises. Retries with capped backoff on 429 / 5xx / transport
    errors; treats any 4xx as a hard failure.
    """
    proxy = _next_proxy()
    attempts = _http_retries()
    for attempt in range(attempts):
        try:
            headers = {"User-Agent": _rotate_ua()}
            headers.update(_BASE_HEADERS)
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT,
                proxy=proxy,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = await client.get(url)
            if resp.status_code in (429,) or resp.status_code >= 500:
                if attempt + 1 < attempts:
                    await asyncio.sleep(_backoff(attempt))
                continue
            if resp.status_code >= 400:
                return None
            return resp.text
        except httpx.HTTPError as exc:
            logger.warning(
                "retail_http_error",
                extra={"url": url[:140], "error": str(exc)[:140], "attempt": attempt},
            )
            if attempt + 1 < attempts:
                await asyncio.sleep(_backoff(attempt))
            continue
    return None


# ── Public API ─────────────────────────────────────────────────────────


async def get_retail_product(store: str, product_id: str) -> dict[str, Any]:
    """Fetch + normalize one retail product; {} on any failure (never raises).

    ``store`` is a registry key or alias (e.g. ``"target"``, ``"best buy"``).
    ``product_id`` is the store-specific id (Target TCIN, Best Buy SKU, …).
    """
    try:
        store_key = _normalize_store(store)
        product_id = (product_id or "").strip()
        if not store_key or not product_id:
            return {}
        info = _STORES[store_key]
        url = _product_url(info, product_id)
        html_text = await _fetch_page(url)
        if not html_text:
            return {}
        record = _parse_product_page(store_key, html_text, product_id, url)
        return record or {}
    except Exception as exc:  # noqa: BLE001 - outermost safety net for a never-raise API
        logger.warning(
            "retail_get_product_failed",
            extra={"store": store, "product_id": str(product_id)[:64], "error": str(exc)[:160]},
        )
        return {}


async def _search_store(store_key: str, query: str, limit: int) -> list[dict[str, Any]]:
    """Search one store and return up to ``limit`` records (never raises)."""
    try:
        info = _STORES[store_key]
        url = info["search_url"].format(q=_url_quote(query))
        html_text = await _fetch_page(url)
        if not html_text:
            return []
        return _parse_search_page(store_key, html_text, limit)
    except Exception as exc:  # noqa: BLE001 - per-store degradation; transport already guarded
        logger.warning(
            "retail_store_search_failed",
            extra={"store": store_key, "query": query[:80], "error": str(exc)[:160]},
        )
        return []


async def search_retail(query: str, store: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    """Search retail stores and return up to ``limit`` records (never raises).

    ``store`` is a registry key / alias, or ``"all"`` (default) to
    aggregate every store concurrently with per-store degradation.
    Returns ``[]`` on any failure, empty query, or unknown store.
    """
    text = (query or "").strip()
    cap = _clamp_limit(limit)
    if not text:
        return []
    try:
        store_key = _normalize_store(store)
        if store_key:
            return await _search_store(store_key, text, cap)
        raw_store = (store or "").strip().lower()
        if raw_store in ("all", ""):
            gathered = await asyncio.gather(
                *[_search_store(key, text, cap) for key in _STORES],
                return_exceptions=True,
            )
            results: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for outcome in gathered:
                if isinstance(outcome, BaseException):
                    continue
                for record in outcome:
                    key = (
                        record.get("store") or "",
                        record.get("product_id") or record.get("title") or "",
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(record)
                    if len(results) >= cap:
                        return results
            return results
        logger.warning("retail_store_unknown", extra={"store": str(store)[:64]})
        return []
    except Exception as exc:  # noqa: BLE001 - outermost safety net for a never-raise API
        logger.warning(
            "retail_search_failed",
            extra={"query": text[:80], "store": str(store)[:64], "error": str(exc)[:160]},
        )
        return []


__all__ = [
    "get_retail_product",
    "search_retail",
]
