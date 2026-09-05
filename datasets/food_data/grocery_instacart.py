"""Instacart store scrape — Apollo state + JSON-LD + signature fallbacks.

No key. Search pages embed product/price data in an Apollo
``__APOLLO_STATE__`` JSON blob; we walk it for ``name`` + ``price`` pairs
(JSON-LD fallback). Instacart is heavily bot-protected, so results are
best-effort.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from datasets.food_data.grocery_common import (
    _EXCLUDED_EXCEPTIONS,
    _HEADERS,
    _TIMEOUT,
    _clean_name,
    _extract_price,
    _safe_float,
    _today,
)

logger = logging.getLogger(__name__)

_INSTACART_SEARCH_URL = "https://www.instacart.com/store/s"

# Instacart embeds Apollo GraphQL state (product nodes with name + price).
_INSTACART_APOLLO_RE = re.compile(r"window\.__APOLLO_STATE__\s*=\s*", re.IGNORECASE)
_INSTACART_BLOCK_RE = re.compile(
    r'\{"name"\s*:\s*"([^"]+)"(?:.*?)"(?:price|display_price)"\s*:\s*([\d.]+)', re.DOTALL
)
# Shared JSON-LD Product/Offer extraction (Instacart + Aldi both embed it).
_JSONLD_RE = re.compile(
    r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL
)


def _walk_named_price(
    node: Any,
    records: list[dict[str, Any]],
    seen: set[tuple[str, float]],
    zip_code: str,
    store: str,
    limit: int,
) -> None:
    """Recursively collect (name, price) product dicts from embedded JSON."""
    if len(records) >= limit:
        return
    if isinstance(node, list):
        for child in node:
            _walk_named_price(child, records, seen, zip_code, store, limit)
            if len(records) >= limit:
                return
        return
    if not isinstance(node, dict):
        return
    name = node.get("name")
    if isinstance(name, str) and name:
        price = _extract_price(
            node.get("price") or node.get("current_price") or node.get("displayPrice")
        )
        if price is not None:
            key = (_clean_name(name), price)
            if key not in seen:
                seen.add(key)
                records.append(
                    {
                        "product": key[0],
                        "store": store,
                        "price": price,
                        "currency": "USD",
                        "zip_code": zip_code,
                        "unit": "each",
                        "date": _today(),
                    }
                )
    for value in node.values():
        _walk_named_price(value, records, seen, zip_code, store, limit)
        if len(records) >= limit:
            return


def _extract_jsonld_products(html_text: str) -> list[tuple[str, float]]:
    """Collect (name, price) pairs from JSON-LD Product/Offer nodes."""
    pairs: list[tuple[str, float]] = []
    for match in _JSONLD_RE.finditer(html_text):
        try:
            payload = json.loads(match.group(1))
        except _EXCLUDED_EXCEPTIONS as exc:
            logger.warning("instacart_jsonld_parse_failed", extra={"error": str(exc)[:120]})
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            offers = node.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if not isinstance(offers, dict):
                continue
            name = _clean_name(node.get("name"))
            price = _safe_float(offers.get("price"))
            if name and price is not None:
                pairs.append((name, price))
    return pairs


def _parse_instacart_html(html_text: str, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Normalize an Instacart search page into the canonical record shape."""
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()

    apollo_match = _INSTACART_APOLLO_RE.search(html_text)
    if apollo_match:
        start = apollo_match.end()
        depth = 0
        in_string = False
        escape = False
        blob_end = len(html_text)
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
                    blob_end = i + 1
                    break
        try:
            state = json.loads(html_text[start:blob_end])
        except _EXCLUDED_EXCEPTIONS as exc:
            logger.warning("instacart_apollo_parse_failed", extra={"error": str(exc)[:120]})
            state = None
        if isinstance(state, dict):
            # Apollo state: product entities live under ROOT_QUERY keyed by
            # search results; walk every value for name+price objects.
            _walk_named_price(state, records, seen, zip_code, "Instacart", limit)

    if records:
        return records[:limit]

    # JSON-LD fallback (Instacart search pages embed Product offers).
    for name, price in _extract_jsonld_products(html_text):
        if not name or (name, price) in seen:
            continue
        seen.add((name, price))
        records.append(
            {
                "product": name,
                "store": "Instacart",
                "price": price,
                "currency": "USD",
                "zip_code": zip_code,
                "unit": "each",
                "date": _today(),
            }
        )
        if len(records) >= limit:
            break
    if records:
        return records[:limit]

    # Signature fallback when the Apollo/JSON-LD shapes change.
    for match in _INSTACART_BLOCK_RE.finditer(html_text):
        name = _clean_name(match.group(1))
        sig_price = _safe_float(match.group(2))
        if not name or sig_price is None or (name, sig_price) in seen:
            continue
        seen.add((name, sig_price))
        records.append(
            {
                "product": name,
                "store": "Instacart",
                "price": sig_price,
                "currency": "USD",
                "zip_code": zip_code,
                "unit": "each",
                "date": _today(),
            }
        )
        if len(records) >= limit:
            break
    return records


async def _instacart_prices(query: str, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Scrape prices from an Instacart search page; [] on any failure.

    Instacart aggressively bot-blocks datacenter traffic, so this source
    frequently returns ``[]`` in practice — treated as best-effort.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(f"{_INSTACART_SEARCH_URL}/{query}")
            if resp.status_code >= 400:
                logger.warning("instacart_http_error", extra={"status": resp.status_code})
                return []
            return _parse_instacart_html(resp.text, zip_code, limit)
    except _EXCLUDED_EXCEPTIONS as exc:
        logger.warning("instacart_prices_failed", extra={"error": str(exc)[:120]})
        return []
