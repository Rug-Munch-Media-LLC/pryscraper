"""Pry — deals + drop-alerts data router.

Exposes deal-aggregator coupon search (Slickdeals / RetailMeNot) and
product restock/price-drop alert monitoring backed by the ``deals_data``
subpackage (built in parallel, so every import is guarded and degrades to
502 while a module has not landed yet).

Endpoints:
- GET /v1/deals/search            — search deals across aggregators
- GET /v1/deals/store/{store}     — deals/coupons for one retailer
- GET /v1/deals/drops/set         — create a product drop/restock alert
- GET /v1/deals/drops/check       — resolve prices + report triggers

This router is NOT wired into api.py yet (the lead wires new routers after
the parallel build lands). It is import-safe standalone.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from typing import Any, NoReturn

from fastapi import APIRouter, Query

from pry.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Deals Data"])


def _coupons_module() -> Any:
    """Import the ``deals_data.coupons`` module with a guarded ImportError.

    The module is created in parallel by another agent; return None when it
    has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module("datasets.deals_data.coupons")
    except ImportError:
        logger.warning("deals_coupons_module_unavailable")
        return None


def _drops_module() -> Any:
    """Import the ``deals_data.drops`` module with a guarded ImportError."""
    try:
        return importlib.import_module("datasets.deals_data.drops")
    except ImportError:
        logger.warning("deals_drops_module_unavailable")
        return None


def _module_unavailable() -> NoReturn:
    raise ExternalServiceError("deals_data is not available yet (parallel build in progress)")


@router.get(
    "/v1/deals/search",
    tags=["Deals Data"],
    summary="Search deals across Slickdeals / RetailMeNot",
)
async def deals_search(
    query: str = Query(..., min_length=1, max_length=500, description="Search term"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search deal aggregators. May return an empty list (anti-bot)."""
    mod = _coupons_module()
    if mod is None:
        _module_unavailable()
    data = await mod.search_deals(query, limit=limit)
    return {"success": True, "data": data, "query": query, "limit": limit}


@router.get(
    "/v1/deals/store/{store}",
    tags=["Deals Data"],
    summary="Deals/coupons for one retailer",
)
async def deals_store(
    store: str,
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Fetch deals/coupons for a retailer slug (e.g. ``amazon``)."""
    mod = _coupons_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_store_deals(store, limit=limit)
    return {"success": True, "data": data, "store": store, "limit": limit}


@router.get(
    "/v1/deals/drops/set",
    tags=["Deals Data"],
    summary="Create a product restock/price-drop alert",
)
async def deals_drops_set(
    product: str = Query(..., min_length=1, max_length=500, description="Product (ASIN or name)"),
    target_price: float | None = Query(None, ge=0, description="Trigger when price <= target"),
    notify_url: str | None = Query(None, max_length=2000, description="Optional webhook URL"),
) -> dict[str, Any]:
    """Register a drop alert for a product."""
    mod = _drops_module()
    if mod is None:
        _module_unavailable()
    data = await mod.set_drop_alert(product, target_price=target_price, notify_url=notify_url)
    return {"success": True, "data": data, "product": product}


@router.get(
    "/v1/deals/drops/check",
    tags=["Deals Data"],
    summary="Resolve prices + report drop-alert trigger state",
)
async def deals_drops_check() -> dict[str, Any]:
    """Re-resolve every alert's price; returns trigger records."""
    mod = _drops_module()
    if mod is None:
        _module_unavailable()
    data = await mod.check_drop_alerts()
    return {"success": True, "data": data, "count": len(data)}
