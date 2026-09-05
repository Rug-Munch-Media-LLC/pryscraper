"""AliExpress marketplace adapter: best-effort scraping of public pages.

AliExpress serves a JS challenge to non-browser clients, so extraction
(from the embedded ``window._dida_config_`` / ``window.runParams`` JSON)
often finds nothing. Treat results as best-effort.

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

from datasets.commerce_data.marketplaces_common import (
    _deep_first,
    _extract_next_data,
    _extract_script_object,
    _meta_content,
    _price_from,
    _url_quote,
    _walk_dicts,
)
from datasets.commerce_data.marketplaces_http import _fetch

_ALIEXPRESS_SEARCH_URL = "https://www.aliexpress.com/w/wholesale-{q}.html"
_ALIEXPRESS_ITEM_URL = "https://www.aliexpress.com/item/{item_id}.html"


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
