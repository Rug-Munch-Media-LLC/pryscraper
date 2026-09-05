"""Admin dashboard, health, metrics, config, and ping endpoints.

Earnings, usage, and issue endpoints live in sibling modules; this module
re-exports them so `admin.py` (and any legacy imports) keep working.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import Body, Query
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest

from pry.api.routers.core.admin import ADMIN_DIR, PRY_DATA_DIR, router

# Re-exported endpoint handlers from split modules (legacy import surface).
from pry.api.routers.core.admin_earnings import (  # noqa: F401
    admin_earnings_apify,
    admin_earnings_cloud,
    admin_earnings_combined,
    admin_revenue,
)
from pry.api.routers.core.admin_issues import (  # noqa: F401
    admin_issue_resolve,
    admin_issues,
)
from pry.api.routers.core.admin_shared import (
    CACHE_HIT_RATIO,
    COST_TOTAL,
    REVENUE_TOTAL,
    SCRAPES_ACTIVE,
    _compute_profits,
    _get_apify_profits,
)
from pry.api.routers.core.admin_usage import (  # noqa: F401
    admin_actors,
    admin_api_usage,
)
from pry.core.deps import automator, cache, ratelimiter

logger = logging.getLogger(__name__)

# Process start time for uptime reporting (avoids blocking os.path calls
# inside async handlers — ASYNC240).
_START_TIME = time.time()


@router.get(
    "/v1/admin/dashboard",
    summary="Complete admin dashboard with profits and health",
)
async def admin_dashboard(
    days: int = Query(30, description="Number of days to look back"),
) -> dict[str, Any]:
    """Get the full admin dashboard: profits, costs, system health, Apify."""
    profits = _compute_profits(days)
    apify = _get_apify_profits()

    # System health
    cache_stats = cache.stats()
    rate_stats = ratelimiter.get_stats()
    hit_rate = cache_stats.get("hit_rate", 0)

    REVENUE_TOTAL.set(profits["x402"]["revenue_usd"])
    COST_TOTAL.set(profits["costs"]["total_operating_cost_usd"])
    CACHE_HIT_RATIO.set(hit_rate)

    return {
        "success": True,
        "profits": profits,
        "apify": apify,
        "system": {
            "cache_hit_rate": hit_rate,
            "active_sessions": len(automator.sessions),
            "total_requests": rate_stats.get("total_requests", 0),
            "active_ips": rate_stats.get("active_ips", 0),
            "blocked_requests": rate_stats.get("total_blocked", 0),
        },
        "period_days": days,
    }


@router.get(
    "/v1/admin/profits",
    summary="Profit breakdown from x402 payments minus costs",
)
async def admin_profits(
    days: int = Query(30, description="Lookback period in days"),
) -> dict[str, Any]:
    """Detailed profit/loss breakdown."""
    return {"success": True, "data": _compute_profits(days)}


@router.get(
    "/v1/admin/health",
    summary="System health check",
)
async def admin_health() -> dict[str, Any]:
    """Health check with component status."""
    cache_stats = cache.stats()
    rate_stats = ratelimiter.get_stats()
    uptime = time.time() - _START_TIME

    return {
        "success": True,
        "status": "healthy",
        "uptime_seconds": uptime,
        "cache": {
            "hit_rate": cache_stats.get("hit_rate", 0),
            "size": cache_stats.get("size", 0),
            "hits": cache_stats.get("hits", 0),
        },
        "rate_limiter": {
            "total_requests": rate_stats.get("total_requests", 0),
            "active_ips": rate_stats.get("active_ips", 0),
        },
        "automator": {
            "available": automator.available,
            "active_sessions": len(automator.sessions),
        },
        "version": "3.0.0",
    }


@router.get(
    "/v1/admin/apify",
    summary="Apify actor profit monitoring",
)
async def admin_apify() -> dict[str, Any]:
    """Fetch profit data from Apify API."""
    return {"success": True, "data": _get_apify_profits()}


@router.get(
    "/v1/admin/metrics",
    summary="Prometheus metrics for Grafana",
    response_class=PlainTextResponse,
)
async def admin_metrics() -> str:
    """Generate Prometheus-formatted metrics for Grafana scraping."""
    # Refresh metrics
    profits = _compute_profits(30)
    cache_stats = cache.stats()
    REVENUE_TOTAL.set(profits["x402"]["revenue_usd"])
    COST_TOTAL.set(profits["costs"]["total_operating_cost_usd"])
    CACHE_HIT_RATIO.set(cache_stats.get("hit_rate", 0))
    SCRAPES_ACTIVE.set(len(automator.sessions))

    return generate_latest().decode("utf-8")


@router.get(
    "/v1/admin/config",
    summary="Show admin configuration status",
)
async def admin_config() -> dict[str, Any]:
    """Show which admin features are configured."""
    return {
        "success": True,
        "apify_api_key_set": bool(os.getenv("APIFY_API_KEY", "")),
        "admin_dir": ADMIN_DIR,
        "data_dir": PRY_DATA_DIR,
        "metrics_enabled": True,
    }


@router.post(
    "/v1/admin/ping",
    summary="Health check with request body",
)
async def admin_ping(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Simple ping-pong for monitoring."""
    return {"success": True, "pong": True, "echo": body}
