"""Pry — Stats router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from deps import automator, cache, ratelimiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Stats"])

@router.get("/v0/stats", tags=["Stats"], summary="Get cache, rate limiter, and session stats")
async def stats() -> dict[str, Any]:
    return {
        "cache": cache.stats(),
        "rate_limiter": ratelimiter.get_stats(),
        "sessions": automator.list_sessions(),
    }
