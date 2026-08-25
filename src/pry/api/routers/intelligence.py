"""Pry — Intelligence router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Intelligence"])


@router.post(
    "/v1/intel/snapshot", tags=["Intelligence"], summary="Record a competitor data snapshot"
)
async def record_intel_snapshot(
    competitor_id: str = Body(...),
    competitor_name: str = Body(...),
    url: str = Body(...),
    fields: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Record a data snapshot for a competitor.

    Snapshots are stored with timestamps and used for trend analysis,
    anomaly detection, and report generation.
    """
    from pry.api.intelligence import record_snapshot

    result = record_snapshot(competitor_id, competitor_name, url, fields)
    return {"success": True, "data": result}


@router.get(
    "/v1/intel/snapshots/{competitor_id}", tags=["Intelligence"], summary="Get competitor snapshots"
)
async def get_intel_snapshots(
    competitor_id: str,
    limit: int = 50,
    since_hours: int | None = None,
) -> dict[str, Any]:
    """Get historical snapshots for a competitor."""
    from pry.api.intelligence import get_snapshots

    snapshots = get_snapshots(competitor_id, limit, since_hours)
    return {
        "success": True,
        "data": {"competitor_id": competitor_id, "snapshots": snapshots, "count": len(snapshots)},
    }


@router.post(
    "/v1/intel/analyze", tags=["Intelligence"], summary="Analyze competitor field for anomalies"
)
async def analyze_field(
    competitor_id: str = Body(...),
    field: str = Body("price"),
) -> dict[str, Any]:
    """Analyze a specific field across a competitor's snapshots for anomalies.

    Returns statistics, z-score analysis, and anomaly detection.
    """
    from pry.api.intelligence import (
        compute_field_statistics,
        detect_anomalies_numeric,
        get_snapshots,
    )

    snapshots = get_snapshots(competitor_id, limit=100)
    stats = compute_field_statistics(snapshots, field)

    if (
        stats.get("has_history")
        and stats.get("latest") is not None
        and stats.get("previous") is not None
    ):
        numeric_vals = [
            s.get("fields", {}).get(field)
            for s in snapshots
            if isinstance(s.get("fields", {}).get(field), (int, float))
        ]
        if len(numeric_vals) >= 3:
            anomaly = detect_anomalies_numeric(numeric_vals[-1], numeric_vals[:-1])
        else:
            anomaly = {"anomaly": False, "reason": "Insufficient numeric history"}
    else:
        anomaly = {"anomaly": False, "reason": "Insufficient data"}

    return {"success": True, "data": {"field": field, "statistics": stats, "anomaly": anomaly}}


@router.post(
    "/v1/intel/report", tags=["Intelligence"], summary="Generate a competitive intelligence report"
)
async def generate_report(
    competitors: list[dict[str, Any]] = Body(...),
    days_back: int = Body(7),
) -> dict[str, Any]:
    """Generate a competitive intelligence report for tracked competitors.

    Analyzes changes over the specified period and returns a structured report
    with a natural-language summary.
    """
    from pry.api.intelligence import generate_weekly_report

    report = generate_weekly_report(competitors, days_back)
    return {"success": True, "data": report}
