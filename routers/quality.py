"""Pry — Quality router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Quality"])


@router.post(
    "/v1/quality/check", tags=["Quality"], summary="Run data quality check on extraction results"
)
async def quality_check(
    url: str = Body(...),
    data: dict[str, Any] = Body(...),
    schema: dict[str, Any] | None = Body(None),
    expected_types: dict[str, str] | None = Body(None),
) -> dict[str, Any]:
    """Run a full data quality check on extraction results.

    Metrics:
    - Completeness: what % of expected fields have values
    - Schema adherence: field types match expectations
    - Freshness: how old is the data
    - Anomaly detection: what changed since last extraction

    Use this to validate data BEFORE sending to downstream systems.
    """
    from quality import run_quality_check

    # Convert string type names to actual types
    type_map: dict[str, type] = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "None": type(None),
    }
    resolved_types: dict[str, type] | None = None
    if expected_types:
        resolved_types = {}
        for field, type_name in expected_types.items():
            resolved_types[field] = type_map.get(type_name, str)

    result = await run_quality_check(
        url=url,
        data=data,
        schema=schema,
        expected_types=resolved_types,
    )
    return {"success": True, "data": result}


@router.get(
    "/v1/quality/stats", tags=["Quality"], summary="Get quality statistics for all checked URLs"
)
async def quality_stats() -> dict[str, Any]:
    """Get aggregate quality statistics across all checked URLs."""
    from quality import QUALITY_DIR

    stats: list[dict[str, Any]] = []
    for path in sorted(QUALITY_DIR.glob("*.json"), key=os.path.getmtime, reverse=True)[:50]:
        try:
            data = json.loads(path.read_text())
            stats.append(
                {
                    "url": data.get("url", ""),
                    "checked_at": data.get("checked_at", ""),
                    "size_bytes": path.stat().st_size,
                }
            )
        except (json.JSONDecodeError, OSError):
            continue

    return {"success": True, "data": {"total_checked": len(stats), "recent": stats}}
