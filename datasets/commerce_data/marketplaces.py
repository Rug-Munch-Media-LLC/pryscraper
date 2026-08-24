"""Commerce long-tail product search/lookup: eBay, Etsy, AliExpress, Shopify.

Sources (all free):

* **eBay** — the Finding API (``findItemsByKeywords``) and Shopping API
  (``GetSingleItem``). Both need a free app key set via the
  ``PRY_EBAY_API_KEY`` env var (https://developer.ebay.com/). Without a
  key every eBay call degrades to ``[]`` / ``{}`` (never raises).
* **Shopify** — the public ``https://{store}.myshopify.com/products.json``
  endpoint (no auth, capped at 250 products per page). ``query`` is the
  store subdomain; ``get_product`` takes ``"store:id"`` or
  ``"store:handle"`` and scans the first page (250 products) for a match.
* **Etsy** — public search / listing pages. No free public API (OAuth
  only), so this scrapes ``__NEXT_DATA__`` / JSON-LD. Etsy aggressively
  blocks datacenter traffic (403 / captcha / login walls), so expect
  frequent ``[]`` / ``{}`` in practice — treat results as best-effort.
* **AliExpress** — public search / item pages. AliExpress serves a JS
  challenge to non-browser clients, so extraction (from the embedded
  ``window._dida_config_`` / ``window.runParams`` JSON) often finds
  nothing. Treat results as best-effort.
* **Target / Best Buy** — routed through :mod:`marketplace.retail`,
  which parses the JSON-LD ``Product`` and embedded ``__NEXT_DATA__``
  state from the public product / search pages (no API keys). Best Buy
  is Akamai-protected and Costco-style geo/JS gates can appear, so
  results degrade to ``[]`` / ``{}`` when blocked (never raise).

Contract
--------
* :func:`search_product` — async, never raises, returns a ``list``
  (``[]`` on failure).
* :func:`get_product` — async, never raises, returns a ``dict``
  (``{}`` on failure).

Canonical result shape::

    {
        "id": str,
        "title": str,
        "price": float | None,
        "currency": str | None,
        "seller": str | None,
        "rating": float | None,   # seller feedback score (eBay); None elsewhere
        "url": str,
        "marketplace": "ebay" | "etsy" | "aliexpress" | "shopify" | "target" | "bestbuy",
    }

Anti-bot honesty: scraping sources are parsed with signature-based
extractors over embedded JSON, mirroring the travel module's approach.
When a site changes layout or blocks the request, output silently
degrades to ``[]`` / ``{}`` — never an exception.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from marketplace import retail as _retail_sources

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

MARKETPLACES = ("ebay", "etsy", "aliexpress", "shopify", "target", "bestbuy")

# Retailers routed through marketplace.retail (JSON-LD / embedded state).
_RETAIL_MARKETPLACES = ("target", "bestbuy")

_MAX_LIMIT = 250  # Shopify products.json caps at 250 per page

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 1

# ── eBay ───────────────────────────────────────────────────────────────
_EBAY_FIND_URL = "https://svcs.ebay.com/services/search/FindingService/v1"
_EBAY_ITEM_URL = "https://open.api.ebay.com/shopping"
_EBAY_API_KEY_ENV = "PRY_EBAY_API_KEY"
_EBAY_NS = {"e": "http://www.ebay.com/marketplace/search/v1/services"}
_EBAY_ITEM_NS = {"s": "http://open.api.ebay.com/shopping"}

# ── Shopify ────────────────────────────────────────────────────────────
_SHOPIFY_STORE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}$")

# ── Etsy / AliExpress ──────────────────────────────────────────────────
_ETSY_SEARCH_URL = "https://www.etsy.com/search?q={q}"
_ETSY_LISTING_URL = "https://www.etsy.com/listing/{listing_id}"
_ALIEXPRESS_SEARCH_URL = "https://www.aliexpress.com/w/wholesale-{q}.html"
_ALIEXPRESS_ITEM_URL = "https://www.aliexpress.com/item/{item_id}.html"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)
_META_PROP_RE = re.compile(r'<meta[^>]+property="([^"]*)"[^>]*content="([^"]*)"', re.DOTALL)


# ── low-level helpers ──────────────────────────────────────────────────


def _api_key() -> str:
    """Return the configured eBay app key, or '' when missing."""
    return os.environ.get(_EBAY_API_KEY_ENV, "").strip()


def _clamp_limit(limit: Any) -> int:
    """Coerce ``limit`` to an int within [1, _MAX_LIMIT]; default 20."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, _MAX_LIMIT))


def _url_quote(query: str) -> str:
    return quote(query, safe="")


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (knobs are test-overridable)."""
    if attempt <= 0 or RETRY_BASE <= 0 or MAX_BACKOFF <= 0:
        return
    await asyncio.sleep(min(MAX_BACKOFF, RETRY_BASE * (2**attempt)))


async def _fetch(url: str, params: dict[str, str] | None = None) -> str:
    """GET a URL with bounded backoff retries; never raises ('' on failure)."""
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.get(url, params=params)
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                return ""
            return resp.text
        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("commerce_fetch_failed", extra={"url": url[:120], "error": last_error})
    return ""


def _to_float(value: Any) -> float | None:
    """Coerce a JSON/text value to float; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _parse_money(text: str | None) -> float | None:
    """Extract a price number from a money string like 'US $1,234.56'."""
    if not text:
        return None
    match = re.search(r"\d[\d.,]*", text)
    if not match:
        return None
    digits = match.group(0).replace(",", "")
    try:
        return float(digits)
    except ValueError:
        return None


def _walk_dicts(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict (at any depth) inside a parsed JSON tree."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _deep_first(obj: Any, keys: tuple[str, ...]) -> Any:
    """First non-None value found for any of ``keys`` at any depth."""
    for d in _walk_dicts(obj):
        for key in keys:
            value = d.get(key)
            if value is not None:
                return value
    return None


def _price_from(obj: Any, keys: tuple[str, ...]) -> float | None:
    """Best-effort price extraction (plain numbers, money strings, or
    ``{"amount": .., "divisor": .., "currency_code": ..}`` dicts)."""
    for d in _walk_dicts(obj):
        for key in keys:
            value = d.get(key)
            if value is None:
                continue
            if isinstance(value, dict):
                amount = value.get("amount")
                divisor = value.get("divisor")
                if (
                    isinstance(amount, (int, float))
                    and isinstance(divisor, (int, float))
                    and divisor
                ):
                    return float(amount) / float(divisor)
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                parsed = _parse_money(value)
                if parsed is not None:
                    return parsed
    return None


def _extract_next_data(raw: str) -> Any:
    """Parse the Next.js ``__NEXT_DATA__`` JSON blob (Etsy search pages)."""
    match = _NEXT_DATA_RE.search(raw)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _extract_script_object(raw: str, marker: str) -> Any:
    """Parse the first JSON object assigned after ``marker`` (string-aware)."""
    idx = raw.find(marker)
    if idx < 0:
        return None
    start = raw.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
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
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _meta_content(raw: str, prop: str) -> str | None:
    """Return the ``content`` of the first ``<meta property="...">`` tag."""
    for p, content in _META_PROP_RE.findall(raw):
        if p == prop and content.strip():
            return html.unescape(content.strip())
    return None


def _elem_text(element: ET.Element, path: str, namespaces: dict[str, str]) -> str | None:
    found = element.find(path, namespaces)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None


# ── eBay ───────────────────────────────────────────────────────────────


def _map_ebay_item(item: ET.Element) -> dict[str, Any] | None:
    """Map a Finding API ``<item>`` onto the canonical record."""
    item_id = _elem_text(item, "e:itemId", _EBAY_NS)
    title = _elem_text(item, "e:title", _EBAY_NS)
    if not item_id and not title:
        return None
    price_el = item.find("e:sellingStatus/e:convertedCurrentPrice", _EBAY_NS)
    if price_el is None:
        price_el = item.find("e:sellingStatus/e:currentPrice", _EBAY_NS)
    price = _to_float(price_el.text if price_el is not None else None)
    currency = price_el.get("currencyId") if price_el is not None else None
    seller = _elem_text(item, "e:sellerInfo/e:sellerUserName", _EBAY_NS)
    rating = _to_float(_elem_text(item, "e:sellerInfo/e:feedbackScore", _EBAY_NS))
    url = _elem_text(item, "e:viewItemURL", _EBAY_NS) or (
        f"https://www.ebay.com/itm/{item_id}" if item_id else ""
    )
    return {
        "id": item_id or "",
        "title": title or "",
        "price": price,
        "currency": currency,
        "seller": seller,
        "rating": rating,
        "url": url,
        "marketplace": "ebay",
    }


async def _ebay_search(query: str, limit: int) -> list[dict[str, Any]]:
    key = _api_key()
    if not key:
        logger.warning("ebay_search_no_api_key", extra={"env": _EBAY_API_KEY_ENV})
        return []
    params = {
        "OPERATION-NAME": "findItemsByKeywords",
        "SERVICE-VERSION": "1.13.0",
        "SECURITY-APPNAME": key,
        "GLOBAL-ID": "EBAY-US",
        "RESPONSE-DATA-FORMAT": "XML",
        "keywords": query,
        "paginationInput.entriesPerPage": str(min(limit, 100)),
        "sortOrder": "BestMatch",
    }
    raw = await _fetch(_EBAY_FIND_URL, params=params)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)  # noqa: S314 - vetted HTTPS response; stdlib ET never resolves external entities
    except ET.ParseError:
        logger.warning("ebay_search_parse_failed")
        return []
    ack = root.findtext("e:ack", namespaces=_EBAY_NS) or ""
    if ack not in ("Success", "Warning"):
        return []
    out: list[dict[str, Any]] = []
    for item in root.findall("e:searchResult/e:item", _EBAY_NS):
        record = _map_ebay_item(item)
        if record:
            out.append(record)
        if len(out) >= limit:
            break
    return out


async def _ebay_get(product_id: str) -> dict[str, Any]:
    key = _api_key()
    if not key:
        logger.warning("ebay_get_no_api_key", extra={"env": _EBAY_API_KEY_ENV})
        return {}
    params = {
        "callname": "GetSingleItem",
        "appid": key,
        "ItemID": product_id,
        "responseencoding": "XML",
        "siteid": "0",
        "IncludeSelector": "Details",
    }
    raw = await _fetch(_EBAY_ITEM_URL, params=params)
    if not raw:
        return {}
    try:
        root = ET.fromstring(raw)  # noqa: S314 - vetted HTTPS response; stdlib ET never resolves external entities
    except ET.ParseError:
        logger.warning("ebay_get_parse_failed")
        return {}
    ack = root.findtext("s:Ack", namespaces=_EBAY_ITEM_NS) or ""
    if ack != "Success":
        return {}
    item = root.find("s:Item", _EBAY_ITEM_NS)
    if item is None:
        return {}
    item_id = _elem_text(item, "s:ItemID", _EBAY_ITEM_NS)
    title = _elem_text(item, "s:Title", _EBAY_ITEM_NS)
    if not item_id and not title:
        return {}
    price_el = item.find("s:ConvertedCurrentPrice", _EBAY_ITEM_NS)
    if price_el is None:
        price_el = item.find("s:CurrentPrice", _EBAY_ITEM_NS)
    price = _to_float(price_el.text if price_el is not None else None)
    currency = price_el.get("currencyID") if price_el is not None else None
    seller = _elem_text(item, "s:Seller/s:UserID", _EBAY_ITEM_NS)
    rating = _to_float(_elem_text(item, "s:Seller/s:FeedbackScore", _EBAY_ITEM_NS))
    url = _elem_text(item, "s:ViewItemURLForNaturalSearch", _EBAY_ITEM_NS) or (
        f"https://www.ebay.com/itm/{item_id}" if item_id else ""
    )
    return {
        "id": item_id or "",
        "title": title or "",
        "price": price,
        "currency": currency,
        "seller": seller,
        "rating": rating,
        "url": url,
        "marketplace": "ebay",
    }


# ── Shopify ────────────────────────────────────────────────────────────


def _map_shopify_product(product: dict[str, Any], store: str) -> dict[str, Any]:
    """Map a ``products.json`` product onto the canonical record."""
    product_id = str(product.get("id") or "")
    title = str(product.get("title") or "")
    handle = str(product.get("handle") or "")
    variants = product.get("variants") or []
    price: float | None = None
    if isinstance(variants, list) and variants and isinstance(variants[0], dict):
        price = _to_float(variants[0].get("price"))
    url = f"https://{store}.myshopify.com/products/{handle}" if handle else ""
    if not product_id and not title:
        return {}
    return {
        "id": product_id,
        "title": title,
        "price": price,
        "currency": None,  # products.json does not expose currency
        "seller": store,
        "rating": None,  # products.json has no rating signal
        "url": url,
        "marketplace": "shopify",
    }


async def _fetch_shopify_products(store: str) -> list[dict[str, Any]]:
    raw = await _fetch(f"https://{store}.myshopify.com/products.json", params={"limit": "250"})
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    products = data.get("products") if isinstance(data, dict) else None
    return products if isinstance(products, list) else []


async def _shopify_search(store: str, limit: int) -> list[dict[str, Any]]:
    store = store.strip().lower()
    if not _SHOPIFY_STORE_RE.fullmatch(store):
        logger.warning("shopify_invalid_store", extra={"store": store[:64]})
        return []
    products = await _fetch_shopify_products(store)
    out: list[dict[str, Any]] = []
    for product in products[:limit]:
        if not isinstance(product, dict):
            continue
        record = _map_shopify_product(product, store)
        if record:
            out.append(record)
    return out


async def _shopify_get(product_id: str) -> dict[str, Any]:
    # product_id must carry the store: "store:id" or "store:handle"
    if ":" not in product_id:
        logger.warning("shopify_get_missing_store", extra={"product_id": product_id[:64]})
        return {}
    store, key = product_id.split(":", 1)
    store = store.strip().lower()
    key = key.strip()
    if not _SHOPIFY_STORE_RE.fullmatch(store) or not key:
        return {}
    products = await _fetch_shopify_products(store)
    for product in products:
        if not isinstance(product, dict):
            continue
        if str(product.get("id")) == key or product.get("handle") == key:
            return _map_shopify_product(product, store)
    return {}


# ── Etsy ───────────────────────────────────────────────────────────────


async def _etsy_search(query: str, limit: int) -> list[dict[str, Any]]:
    raw = await _fetch(_ETSY_SEARCH_URL.format(q=_url_quote(query)))
    if not raw:
        return []
    data = _extract_next_data(raw)
    if data is None:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in _walk_dicts(data):
        listing_id = d.get("listing_id")
        if not isinstance(listing_id, (int, str)) or isinstance(listing_id, bool):
            continue
        lid = str(listing_id)
        if lid in seen:
            continue
        title = _deep_first(d, ("title", "Title"))
        price = _price_from(d, ("price", "raw_price", "amount"))
        if title is None and price is None:
            continue  # not a product record (tracking pixel etc.)
        seen.add(lid)
        seller = _deep_first(d, ("shop_name", "shopName", "seller_name"))
        currency = _deep_first(d, ("currency_code", "currencyCode"))
        out.append(
            {
                "id": lid,
                "title": str(title) if title is not None else "",
                "price": price,
                "currency": currency if isinstance(currency, str) else None,
                "seller": seller if isinstance(seller, str) else None,
                "rating": None,
                "url": f"https://www.etsy.com/listing/{lid}",
                "marketplace": "etsy",
            }
        )
        if len(out) >= limit:
            break
    return out


async def _etsy_get(product_id: str) -> dict[str, Any]:
    raw = await _fetch(_ETSY_LISTING_URL.format(listing_id=product_id))
    if not raw:
        return {}
    title = _meta_content(raw, "og:title")
    description = _meta_content(raw, "og:description")
    url = _meta_content(raw, "og:url") or f"https://www.etsy.com/listing/{product_id}"
    price: float | None = None
    currency: str | None = None
    for match in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', raw, re.DOTALL):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        offers = _deep_first(data, ("offers",))
        if isinstance(offers, dict):
            price = _price_from(offers, ("price", "lowPrice", "highPrice"))
            cur = offers.get("priceCurrency") or offers.get("currency")
            if isinstance(cur, str):
                currency = cur
    seller_match = re.search(r'href="/shop/([A-Za-z0-9_-]+)"', raw)
    seller = seller_match.group(1) if seller_match else None
    if title is None and price is None:
        return {}
    return {
        "id": product_id,
        "title": str(title) if title is not None else (description or ""),
        "price": price,
        "currency": currency,
        "seller": seller,
        "rating": None,
        "url": url or "",
        "marketplace": "etsy",
    }


# ── AliExpress ─────────────────────────────────────────────────────────


async def _aliexpress_search(query: str, limit: int) -> list[dict[str, Any]]:
    raw = await _fetch(_ALIEXPRESS_SEARCH_URL.format(q=_url_quote(query)))
    if not raw:
        return []
    data = _extract_script_object(raw, "window._dida_config_")
    if data is None:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in _walk_dicts(data):
        product_id = d.get("productId") or d.get("product_id")
        if not isinstance(product_id, (int, str)) or isinstance(product_id, bool):
            continue
        pid = str(product_id)
        if pid in seen:
            continue
        title = _deep_first(d, ("subject", "product_title", "title"))
        price = _price_from(d, ("formatedPrice", "price", "salePrice"))
        if title is None and price is None:
            continue
        seen.add(pid)
        seller = _deep_first(d, ("storeName", "seller_name", "store_name"))
        out.append(
            {
                "id": pid,
                "title": str(title) if title is not None else "",
                "price": price,
                "currency": None,
                "seller": seller if isinstance(seller, str) else None,
                "rating": None,
                "url": f"https://www.aliexpress.com/item/{pid}.html",
                "marketplace": "aliexpress",
            }
        )
        if len(out) >= limit:
            break
    return out


async def _aliexpress_get(product_id: str) -> dict[str, Any]:
    raw = await _fetch(_ALIEXPRESS_ITEM_URL.format(item_id=product_id))
    if not raw:
        return {}
    data = (
        _extract_script_object(raw, "window.runParams")
        or _extract_script_object(raw, "window._dida_config_")
        or _extract_next_data(raw)
    )
    title: Any = None
    price: float | None = None
    if data is not None:
        title = _deep_first(data, ("subject", "title", "product_title"))
        price = _price_from(data, ("price", "formatedPrice", "salePrice"))
    title_meta = _meta_content(raw, "og:title") if title is None else None
    final_title = str(title) if title is not None else (title_meta or "")
    if not final_title and price is None:
        return {}
    return {
        "id": product_id,
        "title": final_title,
        "price": price,
        "currency": None,
        "seller": None,
        "rating": None,
        "url": f"https://www.aliexpress.com/item/{product_id}.html",
        "marketplace": "aliexpress",
    }


# ── Target / Best Buy (via marketplace.retail) ────────────────────────


def _retail_to_commerce(record: dict[str, Any], mp: str) -> dict[str, Any] | None:
    """Map a ``marketplace.retail`` record onto the commerce canonical shape."""
    if not record:
        return None
    product_id = str(record.get("product_id") or "").strip()
    if not product_id:
        return None
    return {
        "id": product_id,
        "title": str(record.get("title") or ""),
        "price": record.get("price"),
        "currency": record.get("currency"),
        "seller": record.get("seller"),
        "rating": record.get("rating"),
        "url": str(record.get("url") or ""),
        "marketplace": mp,
    }


async def _retail_search(mp: str, query: str, limit: int) -> list[dict[str, Any]]:
    """Search one retail marketplace via marketplace.retail (never raises)."""
    if _retail_sources is None:
        return []
    records = await _retail_sources.search_retail(query, store=mp, limit=limit)
    out: list[dict[str, Any]] = []
    for record in records:
        mapped = _retail_to_commerce(record, mp)
        if mapped:
            out.append(mapped)
    return out


async def _retail_get(mp: str, product_id: str) -> dict[str, Any]:
    """Fetch one retail product via marketplace.retail (never raises)."""
    if _retail_sources is None:
        return {}
    record = await _retail_sources.get_retail_product(mp, product_id)
    mapped = _retail_to_commerce(record, mp)
    return mapped or {}


# ── public API ─────────────────────────────────────────────────────────


async def search_product(
    query: str, marketplace: str = "ebay", limit: int = 20
) -> list[dict[str, Any]]:
    """Search products across a marketplace. Async, never raises.

    ``marketplace`` is one of ``ebay``, ``etsy``, ``aliexpress``,
    ``shopify``, ``target``, ``bestbuy``.
    For ``shopify``, ``query`` is the store subdomain (e.g. ``"allbirds"``).

    Returns ``[]`` on any failure (missing API key, HTTP error, parse
    failure, unsupported marketplace, empty query).
    """
    text = (query or "").strip()
    mp = (marketplace or "").strip().lower()
    bounded = _clamp_limit(limit)
    if not text:
        return []
    if mp == "ebay":
        return await _ebay_search(text, bounded)
    if mp == "shopify":
        return await _shopify_search(text, bounded)
    if mp == "etsy":
        return await _etsy_search(text, bounded)
    if mp == "aliexpress":
        return await _aliexpress_search(text, bounded)
    if mp in _RETAIL_MARKETPLACES:
        return await _retail_search(mp, text, bounded)
    logger.warning("commerce_marketplace_unknown", extra={"marketplace": mp})
    return []


async def get_product(product_id: str, marketplace: str = "ebay") -> dict[str, Any]:
    """Fetch one product by id. Async, never raises.

    ``marketplace`` is one of ``ebay``, ``etsy``, ``aliexpress``,
    ``shopify``, ``target``, ``bestbuy``.
    For ``shopify``, ``product_id`` must be ``"store:id"`` or
    ``"store:handle"`` (e.g. ``"allbirds:123456789"``) because the public
    products.json endpoint needs the store to know where to look.

    Returns ``{}`` on any failure (missing API key, HTTP error, parse
    failure, unsupported marketplace, empty id, not found).
    """
    text = (product_id or "").strip()
    mp = (marketplace or "").strip().lower()
    if not text:
        return {}
    if mp == "ebay":
        return await _ebay_get(text)
    if mp == "shopify":
        return await _shopify_get(text)
    if mp == "etsy":
        return await _etsy_get(text)
    if mp == "aliexpress":
        return await _aliexpress_get(text)
    if mp in _RETAIL_MARKETPLACES:
        return await _retail_get(mp, text)
    logger.warning("commerce_marketplace_unknown", extra={"marketplace": mp})
    return {}
