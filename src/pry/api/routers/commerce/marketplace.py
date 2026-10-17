"""Pry — Marketplace router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.

Also hosts marketplace-intelligence endpoints backed by the ``marketplace``
subpackage (``amazon``, ``walmart``, ``tiktok_shop``), which is built in
parallel by other agents — every import is guarded and degrades to 502 while
a module has not landed yet.

Endpoints:
- POST /v1/actors/create              — create a marketplace actor
- GET  /v1/actors                     — list marketplace actors
- POST /v1/actors/{actor_id}/run      — run a marketplace actor
- GET  /v1/marketplace/amazon/product/{asin}   — Amazon product by ASIN
- GET  /v1/marketplace/amazon/search           — Amazon keyword search
- GET  /v1/marketplace/walmart/product/{product_id} — Walmart product
- GET  /v1/marketplace/tiktok/trending         — TikTok Shop trending
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import importlib
import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from pry.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Marketplace"])

# Failure code -> HTTP status for actor runs. Never report a failed execution
# as a 200 with success:true.
_RUN_STATUS: dict[str, int] = {
    "not_found": 404,
    "template_not_found": 404,
    "invalid_input": 422,
    "requires_processor": 422,
    "no_template": 409,
    "empty_result": 502,
    "scrape_failed": 502,
    "execution_error": 502,
}


@router.post(
    "/v1/actors/create",
    tags=["Marketplace"],
    summary="Create a new actor",
)
async def create_actor(
    name: str = Body(...),
    description: str = Body(...),
    template_id: str = Body(""),
    code: str = Body(""),
    price_per_run: float = Body(0.0),
    visibility: str = Body("private"),
    schedule_cron: str = Body(""),
    tags: list[str] | None = Body(None),
) -> dict[str, Any]:
    """Create a new actor in the marketplace."""
    from pry.commerce.actor_marketplace import ActorMarketplace, ActorVisibility

    m = ActorMarketplace()
    actor = m.create(
        name,
        description,
        template_id,
        code,
        price_per_run,
        ActorVisibility(visibility),
        schedule_cron,
        tags or [],
    )
    return {"success": True, "data": actor.to_dict()}


@router.get(
    "/v1/actors",
    tags=["Marketplace"],
    summary="List actors in the marketplace",
)
async def list_actors(visibility: str = "", tag: str = "") -> dict[str, Any]:
    """List actors. Filter by visibility (public/private) and tag."""
    from pry.commerce.actor_marketplace import ActorMarketplace

    m = ActorMarketplace()
    return {"success": True, "data": m.list(visibility, tag)}


@router.post(
    "/v1/actors/{actor_id}/run",
    tags=["Marketplace"],
    summary="Run an actor",
)
async def run_actor(actor_id: str, inputs: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
    """Run an actor (a stored actor or any ``ALL_PRESETS`` id).

    Preset ids resolve read-only when the store has no match. A failed or
    empty execution is an HTTP error, never ``success: true, data: {}``.
    """
    from pry.commerce.actor_marketplace import ActorMarketplace

    result = await ActorMarketplace().run(actor_id, inputs or {})
    if not result.get("success"):
        status = _RUN_STATUS.get(str(result.get("code")), 502)
        raise HTTPException(
            status_code=status,
            detail=result.get("error", "Actor run failed"),
        )
    return result


def _marketplace_module(module_name: str) -> Any:
    """Import a ``marketplace`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when a
    module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"datasets.marketplace.{module_name}")
    except ImportError:
        # NOTE: ``extra`` must not use stdlib LogRecord-reserved keys (e.g.
        # "module"), which raise KeyError on plain stdlib loggers.
        logger.warning("marketplace_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"marketplace.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/marketplace/amazon/product/{asin}",
    tags=["Marketplace"],
    summary="Get an Amazon product by ASIN",
)
async def marketplace_amazon_product(asin: str) -> dict[str, Any]:
    """Return price, title, availability, and rating for an Amazon ASIN."""
    mod = _marketplace_module("amazon")
    if mod is None:
        _module_unavailable("amazon")
    data = await mod.get_product(asin)
    return {"success": True, "data": data, "asin": asin}


@router.get(
    "/v1/marketplace/amazon/search",
    tags=["Marketplace"],
    summary="Search Amazon products",
)
async def marketplace_amazon_search(
    query: str = Query(..., min_length=1, description="Search keywords, e.g. 'wireless keyboard'"),
    limit: int = Query(20, ge=1, le=100, description="Max results (default: 20)"),
) -> dict[str, Any]:
    """Search Amazon by keyword and return matching listings."""
    mod = _marketplace_module("amazon")
    if mod is None:
        _module_unavailable("amazon")
    data = await mod.search_products(query, limit=limit)
    return {"success": True, "data": data, "query": query, "limit": limit}


@router.get(
    "/v1/marketplace/walmart/product/{product_id}",
    tags=["Marketplace"],
    summary="Get a Walmart product by product ID",
)
async def marketplace_walmart_product(product_id: str) -> dict[str, Any]:
    """Return price, title, availability, seller, and rating for a Walmart product."""
    mod = _marketplace_module("walmart")
    if mod is None:
        _module_unavailable("walmart")
    data = await mod.get_product(product_id)
    return {"success": True, "data": data, "product_id": product_id}


@router.get(
    "/v1/marketplace/tiktok/trending",
    tags=["Marketplace"],
    summary="Get TikTok Shop trending products",
)
async def marketplace_tiktok_trending(
    limit: int = Query(50, ge=1, le=500, description="Max results (default: 50)"),
) -> dict[str, Any]:
    """Return currently trending TikTok Shop products."""
    mod = _marketplace_module("tiktok_shop")
    if mod is None:
        _module_unavailable("tiktok_shop")
    data = await mod.get_trending(limit=limit)
    return {"success": True, "data": data, "limit": limit}
