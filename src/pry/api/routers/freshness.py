"""Pry — Freshness router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Freshness"])


@router.post(
    "/v1/freshness/check",
    tags=["Freshness"],
    summary="Check if content has changed since last scrape",
)
async def freshness_check(
    url: str = Body(...),
    content: str = Body(""),
) -> dict[str, Any]:
    """Check if content has changed since the last scrape.

    Uses content fingerprinting (SHA256) to detect changes.
    If no content is provided, does a quick HEAD check instead.
    """
    from pry.commerce.freshness import (
        check_content_changed,
        quick_health_check,
        record_check_result,
    )

    if content:
        result = await check_content_changed(url, content)
        record_check_result(url, result["changed"])
        return {"success": True, "data": result}

    # Quick HEAD check
    head = await quick_health_check(url)
    return {"success": True, "data": head}


@router.post(
    "/v1/freshness/frequency",
    tags=["Freshness"],
    summary="Get adaptive scrape frequency recommendation",
)
async def freshness_frequency(
    url: str = Body(...),
    base_interval: int = Body(60),
) -> dict[str, Any]:
    """Get an adaptive scrape frequency recommendation based on content volatility.

    Volatile pages (frequent changes) get shorter intervals.
    Stable pages get longer intervals to save costs.
    """
    from pry.commerce.freshness import calculate_adaptive_frequency

    result = calculate_adaptive_frequency(url, base_interval_minutes=base_interval)
    return {"success": True, "data": result}


@router.get(
    "/v1/freshness/dashboard", tags=["Freshness"], summary="Get content staleness dashboard"
)
async def freshness_dashboard() -> dict[str, Any]:
    """Get the content staleness dashboard.

    Shows all tracked URLs, their last check time, age, and whether
    they're stale (not checked in 24h).
    """
    from pry.commerce.freshness import get_staleness_dashboard

    return {"success": True, "data": get_staleness_dashboard()}
