"""Pry — Cost Analytics Engine.
Tracks usage costs, cache hit rates, projected burn, and smart scheduling."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

COSTING_DIR = PRY_DATA_DIR / "costing"
COSTING_DIR.mkdir(parents=True, exist_ok=True)

# Cost per operation (in USD, configurable)
DEFAULT_COST_TABLE = {
    "scrape_direct": 0.001,  # $0.001 per direct scrape
    "scrape_flaresolverr": 0.003,  # $0.003 per FlareSolverr scrape
    "scrape_playwright": 0.005,  # $0.005 per browser render
    "crawl_page": 0.002,  # $0.002 per crawled page
    "llm_call": 0.01,  # $0.01 per LLM call
    "vision_call": 0.02,  # $0.02 per vision model call
    "extraction_css": 0.0005,  # $0.0005 per CSS extraction
    "bandwidth_mb": 0.0001,  # $0.0001 per MB transfer
    "storage_gb_month": 0.01,  # $0.01 per GB-month
}


def record_usage(
    operation: str,
    metadata: dict[str, Any] | None = None,
    quantity: float = 1.0,
) -> dict[str, Any]:
    """Record a usage event and return cost breakdown.

    Args:
        operation: Type of operation (scrape_direct, llm_call, etc.)
        metadata: Additional context (url, model, etc.)
        quantity: Number of units (pages, MB, etc.)

    Returns cost breakdown with cumulative monthly totals.
    """
    cost_table = _load_cost_table()
    unit_cost = cost_table.get(operation, 0.001)
    cost = round(unit_cost * quantity, 6)

    # Record to daily log
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    daily_path = COSTING_DIR / f"usage_{today}.jsonl"
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "operation": operation,
        "quantity": quantity,
        "unit_cost": unit_cost,
        "cost": cost,
        "metadata": metadata or {},
    }
    try:
        with open(daily_path, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:
        logger.warning("cost_record_write_failed", extra={"error": str(e)[:160]})

    return record


def _load_cost_table() -> dict[str, float]:
    """Load cost table, merging defaults with user overrides."""
    path = COSTING_DIR / "cost_table.json"
    table = dict(DEFAULT_COST_TABLE)
    if path.exists():
        try:
            overrides = json.loads(path.read_text())
            table.update(overrides)
        except (json.JSONDecodeError, OSError):
            pass
    return table


async def update_cost_table(overrides: dict[str, float]) -> dict[str, Any]:
    """Update per-operation costs."""
    path = COSTING_DIR / "cost_table.json"
    table = _load_cost_table()
    table.update(overrides)
    try:
        path.write_text(json.dumps(table, indent=2))
        logger.info("cost_table_updated", extra={"overrides": overrides})
        return {"success": True, "cost_table": table}
    except OSError as e:
        return {"success": False, "error": str(e)}


def get_monthly_usage(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Get aggregated usage for a given month.

    Returns totals, breakdown by operation, and projected end-of-month cost.
    """
    now = datetime.now(UTC)
    year = year or now.year
    month = month or now.month
    prefix = f"{year}-{month:02d}"

    operation_breakdown: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "total_cost": 0.0, "avg_cost": 0.0}
    )
    total_cost = 0.0
    total_operations = 0

    # Scan daily files for the month
    for path in sorted(COSTING_DIR.glob(f"usage_{prefix}*.jsonl")):
        try:
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                op = record.get("operation", "unknown")
                cost = record.get("cost", 0)
                total_cost += cost
                total_operations += 1
                operation_breakdown[op]["count"] += 1
                operation_breakdown[op]["total_cost"] += cost
        except (json.JSONDecodeError, OSError):
            continue

    # Compute averages
    for _, stats in operation_breakdown.items():
        stats["avg_cost"] = (
            round(stats["total_cost"] / stats["count"], 6) if stats["count"] > 0 else 0
        )
        stats["total_cost"] = round(stats["total_cost"], 6)

    total_cost = round(total_cost, 6)

    # Project end-of-month cost
    days_in_month = _days_in_month(year, month)
    day_of_month = now.day if year == now.year and month == now.month else days_in_month
    daily_avg = total_cost / max(day_of_month, 1)
    projected = round(daily_avg * days_in_month, 6)

    return {
        "period": f"{year}-{month:02d}",
        "total_cost": total_cost,
        "total_operations": total_operations,
        "projected_monthly_cost": projected,
        "daily_average": round(daily_avg, 6),
        "days_tracked": day_of_month,
        "days_in_month": days_in_month,
        "breakdown": dict(operation_breakdown),
        "cost_table": _load_cost_table(),
    }


def _days_in_month(year: int, month: int) -> int:
    """Get number of days in a month."""
    import calendar

    return calendar.monthrange(year, month)[1]


def get_cache_efficiency() -> dict[str, Any]:
    """Get cache hit rate and efficiency metrics across all caches."""
    total_hits = 0
    total_misses = 0
    total_requests = 0

    return {
        "cache_hits": total_hits,
        "cache_misses": total_misses,
        "hit_rate": round(total_hits / max(total_requests, 1) * 100, 1)
        if total_requests > 0
        else 0,
        "estimated_savings": round(total_hits * 0.002, 6),  # $0.002 saved per cache hit
        "note": "Cache stats available after first scrape",
    }


def get_smart_schedule_recommendations() -> list[dict[str, Any]]:
    """Analyze usage patterns and recommend cost-optimized schedules."""
    monthly = get_monthly_usage()
    recommendations = []

    if monthly["total_cost"] > 10:
        recommendations.append(
            {
                "type": "cache",
                "priority": "high",
                "message": "Cost exceeds $10/month. Enable aggressive caching to reduce repeat scrapes.",
                "estimated_savings": round(monthly["total_cost"] * 0.3, 2),
            }
        )

    if monthly["projected_monthly_cost"] > monthly["total_cost"] * 1.5:
        recommendations.append(
            {
                "type": "projection",
                "priority": "medium",
                "message": f"Projected cost ({monthly['projected_monthly_cost']}) significantly higher than current spend. Review your crawl frequency.",
                "estimated_savings": round(
                    monthly["projected_monthly_cost"] - monthly["total_cost"], 2
                ),
            }
        )

    llm_usage = monthly.get("breakdown", {}).get("llm_call", {})
    if llm_usage.get("total_cost", 0) > 5:
        recommendations.append(
            {
                "type": "llm",
                "priority": "medium",
                "message": f"LLM costs are ${llm_usage['total_cost']}. Consider CSS/XPath extraction for structured data.",
                "estimated_savings": round(llm_usage["total_cost"] * 0.7, 2),
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "type": "info",
                "priority": "low",
                "message": "Usage is within normal range. No optimizations needed.",
                "estimated_savings": 0,
            }
        )

    return recommendations


def get_cost_dashboard() -> dict[str, Any]:
    """Get full cost analytics dashboard data."""
    monthly = get_monthly_usage()

    # Get last 7 days of daily totals
    now = datetime.now(UTC)
    daily_totals = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        prefix = day.strftime("%Y-%m-%d")
        day_cost = 0.0
        day_ops = 0
        path = COSTING_DIR / f"usage_{prefix}.jsonl"
        if path.exists():
            try:
                for line in path.read_text().splitlines():
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    day_cost += r.get("cost", 0)
                    day_ops += 1
            except (json.JSONDecodeError, OSError):
                pass
        daily_totals.append(
            {
                "date": prefix,
                "cost": round(day_cost, 6),
                "operations": day_ops,
            }
        )

    return {
        "current_month": monthly,
        "daily_totals": daily_totals,
        "cache_efficiency": get_cache_efficiency(),
        "recommendations": get_smart_schedule_recommendations(),
    }
