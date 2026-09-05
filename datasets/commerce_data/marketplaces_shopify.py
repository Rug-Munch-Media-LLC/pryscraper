"""Shopify marketplace adapter: public ``products.json`` endpoint.

No auth, capped at 250 products per page. ``query`` is the store
subdomain; ``get_product`` takes ``"store:id"`` or ``"store:handle"``
and scans the first page (250 products) for a match.

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
import logging
import re
from typing import Any

from datasets.commerce_data.marketplaces_common import _to_float
from datasets.commerce_data.marketplaces_http import _fetch

logger = logging.getLogger(__name__)

_SHOPIFY_STORE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}$")


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
