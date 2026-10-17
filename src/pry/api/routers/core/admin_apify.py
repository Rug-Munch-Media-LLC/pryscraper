"""Apify revenue aggregation for the admin dashboard."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    from pry.api.routers.core.admin_shared import APIFY_PROFIT
except ImportError:  # pragma: no cover - metrics optional
    APIFY_PROFIT = None


def _get_apify_profits() -> dict[str, Any]:
    """Fetch profit data from Apify API if configured."""
    api_key = os.getenv("APIFY_API_KEY", "")
    if not api_key:
        return {
            "configured": False,
            "message": "Set APIFY_API_KEY to enable Apify profit tracking",
            "actors": [],
            "total_profit_usd": 0,
        }
    try:
        import httpx

        # Apify API: list actor runs and compute cost/profit
        resp = httpx.get(
            "https://api.apify.com/v2/actor-runs/",
            params={"limit": 50, "status": "SUCCEEDED"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"configured": True, "error": f"Apify API: {resp.status_code}", "actors": []}

        data = resp.json()
        runs = data.get("data", [])
        actors: dict[str, dict[str, Any]] = {}
        total_profit = 0.0
        for run in runs:
            aid = run.get("actId", "unknown")
            if aid not in actors:
                actors[aid] = {
                    "id": aid,
                    "name": run.get("actName", aid),
                    "runs": 0,
                    "total_cost_usd": 0,
                    "total_compute_units": 0,
                }
            actors[aid]["runs"] += 1
            cost = run.get("usageTotalUsd", 0) or 0
            actors[aid]["total_cost_usd"] += cost
            actors[aid]["total_compute_units"] += run.get("usageTotalCu", 0) or 0
            total_profit += cost

        if APIFY_PROFIT is not None:
            APIFY_PROFIT.set(total_profit)
        return {
            "configured": True,
            "actors": list(actors.values()),
            "total_profit_usd": round(total_profit, 2),
            "total_runs": len(runs),
        }
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        logger.warning("apify_profit_fetch_failed", extra={"error": str(e)})
        return {"configured": True, "error": str(e), "actors": []}
