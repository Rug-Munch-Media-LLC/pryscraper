"""Retail marketplace scrapers — Target, Best Buy, Costco, Home Depot, Lowe's, Macy's, Kohl's, Staples.

Keyless, free-tier product search + lookup for the big US general
retailers, mirroring the ``marketplace.amazon`` / ``marketplace.walmart``
approach: fetch the public product / search page and parse whatever the
server embeds — JSON-LD ``Product`` / ``ItemList`` first, then the
Next.js ``__NEXT_DATA__`` state and the ``window.__INITIAL_STATE__`` /
``__PRELOADED_STATE__`` / ``__APOLLO_STATE__`` redux blobs, then
OpenGraph meta tags as a last resort. No API keys anywhere.

Implementation is split across cohesive modules:

* :mod:`pry.commerce.marketplace._retail_stores` — store registry,
  aliases, URL builders, HTTP configuration.
* :mod:`pry.commerce.marketplace._retail_parsing` — embedded-JSON
  extraction (JSON-LD / ``__NEXT_DATA__`` / redux state / OpenGraph) and
  normalization onto the canonical record shape.
* :mod:`pry.commerce.marketplace._retail_transport` — httpx transport
  with stealth user-agent rotation, retry/backoff, and optional Webshare
  residential proxy.

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
import logging
from typing import Any

from pry.commerce.marketplace._retail_parsing import _parse_product_page, _parse_search_page
from pry.commerce.marketplace._retail_stores import (
    _STORES,
    _clamp_limit,
    _normalize_store,
    _product_url,
    _url_quote,
)
from pry.commerce.marketplace._retail_transport import _fetch_page

logger = logging.getLogger(__name__)

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
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
        logger.warning(
            "retail_search_failed",
            extra={"query": text[:80], "store": str(store)[:64], "error": str(exc)[:160]},
        )
        return []


__all__ = [
    "get_retail_product",
    "search_retail",
]
