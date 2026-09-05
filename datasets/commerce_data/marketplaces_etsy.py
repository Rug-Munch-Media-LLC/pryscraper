"""Etsy marketplace adapter: best-effort scraping of public pages.

No free public API (OAuth only), so this scrapes ``__NEXT_DATA__`` /
JSON-LD. Etsy aggressively blocks datacenter traffic (403 / captcha /
login walls), so expect frequent ``[]`` / ``{}`` in practice — treat
results as best-effort.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import re
from typing import Any

from datasets.commerce_data.marketplaces_common import (
    _deep_first,
    _extract_next_data,
    _meta_content,
    _price_from,
    _url_quote,
    _walk_dicts,
)
from datasets.commerce_data.marketplaces_http import _fetch

_ETSY_SEARCH_URL = "https://www.etsy.com/search?q={q}"
_ETSY_LISTING_URL = "https://www.etsy.com/listing/{listing_id}"


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
