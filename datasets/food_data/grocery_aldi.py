"""Aldi / regional store scrape — JSON-LD offers with signature fallback.

No key. Search pages embed JSON-LD product offers; we extract ``name``/
``price`` pairs with a signature fallback. Aldi is a regional chain (US
storefront), so a ZIP in a region Aldi does not serve will naturally
return ``[]`` — best-effort.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from datasets.food_data.grocery_common import (
    _EXCLUDED_EXCEPTIONS,
    _HEADERS,
    _TIMEOUT,
    _clean_name,
    _safe_float,
    _today,
)
from datasets.food_data.grocery_instacart import _extract_jsonld_products

logger = logging.getLogger(__name__)

_ALDI_SEARCH_URL = "https://www.aldi.us/en/search"

# Aldi embeds JSON-LD product offers on search pages.
_ALDI_BLOCK_RE = re.compile(
    r'"(?:name|title)"\s*:\s*"([^"]+)"(?:.*?)"(?:price|lowPrice)"\s*:\s*"([\d.]+)', re.DOTALL
)


def _parse_aldi_html(html_text: str, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Normalize an Aldi US search page into the canonical record shape."""
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()

    for name, price in _extract_jsonld_products(html_text):
        if not name or (name, price) in seen:
            continue
        seen.add((name, price))
        records.append(
            {
                "product": name,
                "store": "Aldi",
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

    # Signature fallback when the JSON-LD shape changes.
    for match in _ALDI_BLOCK_RE.finditer(html_text):
        name = _clean_name(match.group(1))
        sig_price = _safe_float(match.group(2))
        if not name or sig_price is None or (name, sig_price) in seen:
            continue
        seen.add((name, sig_price))
        records.append(
            {
                "product": name,
                "store": "Aldi",
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


async def _aldi_prices(query: str, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Scrape prices from an Aldi US search page; [] on any failure.

    Aldi is a regional chain — a ZIP outside its service area will naturally
    return ``[]``, and the storefront blocks datacenter traffic. Best-effort.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(_ALDI_SEARCH_URL, params={"q": query})
            if resp.status_code >= 400:
                logger.warning("aldi_http_error", extra={"status": resp.status_code})
                return []
            return _parse_aldi_html(resp.text, zip_code, limit)
    except _EXCLUDED_EXCEPTIONS as exc:
        logger.warning("aldi_prices_failed", extra={"error": str(exc)[:120]})
        return []
