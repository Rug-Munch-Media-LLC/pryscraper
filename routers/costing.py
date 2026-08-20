"""Pry — Costing router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Costing"])


@router.get("/v1/costing/dashboard", tags=["Costing"], summary="Get cost analytics dashboard")
async def cost_dashboard() -> dict[str, Any]:
    """Get the full cost analytics dashboard.

    Includes:
    - Monthly spend breakdown by operation type
    - Projected end-of-month cost
    - Daily spend for last 7 days
    - Cache efficiency metrics
    - Smart schedule recommendations
    """
    from costing import get_cost_dashboard

    return {"success": True, "data": get_cost_dashboard()}


@router.get("/v1/costing/usage", tags=["Costing"], summary="Get usage breakdown")
async def cost_usage(
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    """Get detailed usage breakdown for a specific month."""
    from costing import get_monthly_usage

    return {"success": True, "data": get_monthly_usage(year, month)}


@router.post("/v1/costing/record", tags=["Costing"], summary="Record a usage event")
async def record_usage_endpoint(
    operation: str = Body(...),
    quantity: float = Body(1.0),
    metadata: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Record a usage event for cost tracking.

    Operations: scrape_direct, scrape_flaresolverr, scrape_playwright,
    crawl_page, llm_call, vision_call, extraction_css, bandwidth_mb
    """
    from costing import record_usage

    result = record_usage(operation, metadata, quantity)
    return {"success": True, "data": result}


@router.post("/v1/costing/costs", tags=["Costing"], summary="Update per-operation cost table")
async def update_costs(costs: dict[str, float] = Body(...)) -> dict[str, Any]:
    """Update the per-operation cost table with custom prices."""
    from costing import update_cost_table

    result = await update_cost_table(costs)
    return {"success": result["success"], "data": result}
