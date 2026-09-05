"""Walmart store scrape — REDUX JSON extraction with signature fallback.

No key, no quota. The search page embeds product/price data in the
``window.__WML_REDUX_INITIAL_STATE__`` JSON blob; we extract ``name``/
``price`` pairs by walking that JSON (with a signature regex fallback for
layout changes). Walmart aggressively blocks datacenter traffic, so this
frequently returns ``[]`` in practice — treat results as best-effort.

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

_WALMART_SEARCH_URL = "https://www.walmart.com/search"

# Walmart embeds product state in a single REDUX script.
_WALMART_REDUX_RE = re.compile(r"window\.__WML_REDUX_INITIAL_STATE__\s*=\s*", re.IGNORECASE)
# Fallback: flat JSON-ish product blocks containing name + currentPrice.
_WALMART_BLOCK_RE = re.compile(
    r'\{"name"\s*:\s*"([^"]+)"(?:.*?)"currentPrice"\s*:\s*([\d.]+)', re.DOTALL
)


def _walmart_redux_json(html_text: str) -> str:
    """Slice the REDUX state JSON out of a Walmart page (brace-matched)."""
    match = _WALMART_REDUX_RE.search(html_text)
    if not match:
        return ""
    start = match.end()
    if start >= len(html_text) or html_text[start] != "{":
        return ""
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
                return html_text[start : i + 1]
    return ""


def _walk_products(
    node: Any,
    records: list[dict[str, Any]],
    seen: set[tuple[str, float]],
    zip_code: str,
    limit: int,
) -> None:
    """Recursively collect Walmart product dicts (name + price) from REDUX JSON."""
    if len(records) >= limit:
        return
    if isinstance(node, list):
        for child in node:
            _walk_products(child, records, seen, zip_code, limit)
            if len(records) >= limit:
                return
        return
    if not isinstance(node, dict):
        return
    name = node.get("name")
    if isinstance(name, str) and name and "price" in node:
        price = _extract_price(node.get("price"))
        if price is not None:
            key = (_clean_name(name), price)
            if key not in seen:
                seen.add(key)
                records.append(
                    {
                        "product": key[0],
                        "store": "Walmart",
                        "price": price,
                        "currency": "USD",
                        "zip_code": zip_code,
                        "unit": "each",
                        "date": _today(),
                    }
                )
    for value in node.values():
        _walk_products(value, records, seen, zip_code, limit)
        if len(records) >= limit:
            return


def _parse_walmart_html(html_text: str, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Normalize a Walmart search page into the canonical record shape."""
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    redux = _walmart_redux_json(html_text)
    if redux:
        try:
            _walk_products(json.loads(redux), records, seen, zip_code, limit)
        except _EXCLUDED_EXCEPTIONS as exc:
            logger.warning("walmart_redux_parse_failed", extra={"error": str(exc)[:120]})
    if records:
        return records[:limit]
    # Signature fallback when the REDUX blob shape changes.
    for match in _WALMART_BLOCK_RE.finditer(html_text):
        name = _clean_name(match.group(1))
        price = _safe_float(match.group(2))
        if not name or price is None or (name, price) in seen:
            continue
        seen.add((name, price))
        records.append(
            {
                "product": name,
                "store": "Walmart",
                "price": price,
                "currency": "USD",
                "zip_code": zip_code,
                "unit": "each",
                "date": _today(),
            }
        )
        if len(records) >= limit:
            break
    return records


async def _walmart_prices(query: str, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Scrape prices from a Walmart search page; [] on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(_WALMART_SEARCH_URL, params={"q": query})
            if resp.status_code >= 400:
                logger.warning("walmart_http_error", extra={"status": resp.status_code})
                return []
            return _parse_walmart_html(resp.text, zip_code, limit)
    except _EXCLUDED_EXCEPTIONS as exc:
        logger.warning("walmart_prices_failed", extra={"error": str(exc)[:120]})
        return []
