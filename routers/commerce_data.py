"""Pry — commerce long-tail + social data router.

Exposes product search/lookup (eBay, Etsy, AliExpress, Shopify) and
public-profile social follower metrics (Instagram, TikTok, X, YouTube)
backed by the ``commerce_data`` subpackage (built in parallel by other
agents, so every import is guarded and degrades to 502 while a module
has not landed yet).

Endpoints:
- GET /v1/commerce/search                 — product search across a marketplace
- GET /v1/commerce/{marketplace}/{product_id} — single product lookup
- GET /v1/social/{platform}/{handle}      — public follower metrics

For Shopify, ``query`` is the store subdomain (e.g. ``allbirds``) and
``product_id`` is ``"store:id"`` / ``"store:handle"`` because the public
products.json endpoint needs the store to know where to look.

This router is NOT wired into api.py yet (the lead wires new routers
after the parallel build lands). It is import-safe standalone.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from typing import Any

from fastapi import APIRouter, Query

from pry.core.errors import ExternalServiceError, InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Commerce Data"])

_MARKETPLACES = {"ebay", "etsy", "aliexpress", "shopify"}
_PLATFORMS = {"instagram", "tiktok", "twitter", "x", "youtube"}


def _commerce_module(module_name: str) -> Any:
    """Import a ``commerce_data`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when
    a module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"commerce_data.{module_name}")
    except ImportError:
        logger.warning("commerce_data_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"commerce_data.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/commerce/search",
    tags=["Commerce Data"],
    summary="Search products across eBay, Etsy, AliExpress, or a Shopify store",
)
async def commerce_search(
    query: str = Query(
        ..., min_length=1, description="Search term; for shopify: the store subdomain"
    ),
    marketplace: str = Query("ebay", description="ebay | etsy | aliexpress | shopify"),
    limit: int = Query(20, ge=1, le=250, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search products on a marketplace. Returns a list of product records."""
    mp = marketplace.strip().lower()
    if mp not in _MARKETPLACES:
        raise InvalidRequestError(f"marketplace must be one of {sorted(_MARKETPLACES)}")
    mod = _commerce_module("marketplaces")
    if mod is None:
        _module_unavailable("marketplaces")
    data = await mod.search_product(query, marketplace=mp, limit=limit)
    return {
        "success": True,
        "data": data,
        "query": query,
        "marketplace": mp,
        "limit": limit,
    }


@router.get(
    "/v1/commerce/{marketplace}/{product_id}",
    tags=["Commerce Data"],
    summary="Get a single product by id on a marketplace",
)
async def commerce_get_product(marketplace: str, product_id: str) -> dict[str, Any]:
    """Fetch one product. For shopify, product_id must be 'store:id' or 'store:handle'."""
    mp = marketplace.strip().lower()
    if mp not in _MARKETPLACES:
        raise InvalidRequestError(f"marketplace must be one of {sorted(_MARKETPLACES)}")
    mod = _commerce_module("marketplaces")
    if mod is None:
        _module_unavailable("marketplaces")
    data = await mod.get_product(product_id, marketplace=mp)
    return {"success": True, "data": data, "marketplace": mp, "product_id": product_id}


@router.get(
    "/v1/social/{platform}/{handle}",
    tags=["Commerce Data"],
    summary="Public follower metrics for a social profile",
)
async def social_metrics(platform: str, handle: str) -> dict[str, Any]:
    """Return follower metrics for a public profile (partial data on login walls)."""
    pl = platform.strip().lower()
    if pl not in _PLATFORMS:
        raise InvalidRequestError(f"platform must be one of {sorted(_PLATFORMS)}")
    mod = _commerce_module("social")
    if mod is None:
        _module_unavailable("social")
    data = await mod.get_social_metrics(handle, platform=pl)
    return {"success": True, "data": data, "platform": pl, "handle": handle}
