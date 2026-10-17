"""Pry — Stats router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Response

from pry.core.deps import automator, cache, ratelimiter

logger = logging.getLogger(__name__)

# /v0/stats is pre-v1 surface. Removal is announced on every response so
# clients can migrate off it without reading the changelog.
SUNSET_STATS = "Sun, 18 Apr 2027 00:00:00 GMT"

router = APIRouter(tags=["Stats"])


@router.get(
    "/v0/stats",
    tags=["Stats"],
    summary="Get cache, rate limiter, and session stats (deprecated; sunset 2027-04-18)",
    deprecated=True,
)
async def stats(response: Response) -> dict[str, Any]:
    """DEPRECATED pre-v1 stats aggregate — removed on **2027-04-18** (``SUNSET_STATS``).

    Migration: read infrastructure counters from ``/metrics`` (Prometheus
    exposition) and per-key usage from ``GET /v1/account/api-keys/stats``.
    """
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = SUNSET_STATS
    response.headers["Link"] = '</metrics>; rel="successor-version"'
    return {
        "cache": cache.stats(),
        "rate_limiter": ratelimiter.get_stats(),
        "sessions": automator.list_sessions(),
    }
