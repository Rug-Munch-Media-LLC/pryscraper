"""Target / Best Buy adapters, routed through :mod:`pry.commerce.marketplace.retail`.

``retail`` parses the JSON-LD ``Product`` and embedded ``__NEXT_DATA__``
state from the public product / search pages (no API keys). Best Buy is
Akamai-protected and Costco-style geo/JS gates can appear, so results
degrade to ``[]`` / ``{}`` when blocked (never raise).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from pry.commerce.marketplace import retail as _retail_sources


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
