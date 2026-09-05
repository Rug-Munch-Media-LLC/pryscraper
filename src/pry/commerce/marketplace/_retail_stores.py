"""Retail store registry, aliases, URL builders, and HTTP configuration.

Shared by the retail marketplace scrapers (see :mod:`pry.commerce.marketplace.retail`).

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

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
    return str(info["product_url"]).format(product_id=quote(product_id, safe="/"))


def _absolute(store_key: str, value: Any) -> str:
    """Turn a relative product URL into an absolute one for the store host."""
    from pry.commerce.marketplace import _text

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
