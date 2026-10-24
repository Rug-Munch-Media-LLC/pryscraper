"""Pry — attention & SEO intelligence router.

Exposes SERP rank tracking (organic + AI Overview + People Also Ask),
Google Trends interest, and Meta Ad Library ad intelligence backed by the
``attention`` subpackage (built in parallel by other agents, so every
import is guarded and degrades to 502 while a module has not landed yet).

Endpoints:
- GET /v1/attention/serp     — Google SERP scrape (organic + AI Overview + PAA)
- GET /v1/attention/trends   — Google Trends interest over time + related
- GET /v1/attention/ads      — Meta Ad Library active-ad search
- GET /v1/attention/x/posts  — public X/Twitter posts (profile/status/thread/search)
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from typing import Any

from fastapi import APIRouter, Query

from pry.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Attention"])


def _attention_module(module_name: str) -> Any:
    """Import an ``attention`` submodule with a guarded ImportError.

    The modules are created in parallel by other agents; return None when
    a module has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module(f"datasets.attention.{module_name}")
    except ImportError:
        logger.warning("attention_module_unavailable", extra={"module_name": module_name})
        return None


def _module_unavailable(module_name: str) -> None:
    raise ExternalServiceError(
        f"attention.{module_name} is not available yet (parallel build in progress)"
    )


@router.get(
    "/v1/attention/serp",
    tags=["Attention"],
    summary="Scrape Google SERP: organic results, AI Overview, People Also Ask",
)
async def attention_serp(
    q: str = Query(..., description="Search query"),
    num: int = Query(10, ge=1, le=100, description="Max organic results (default: 10)"),
) -> dict[str, Any]:
    """Return organic SERP results, the AI Overview text, and PAA questions."""
    mod = _attention_module("serp")
    if mod is None:
        _module_unavailable("serp")
    data = await mod.serp(q, num=num)
    return {"success": "error" not in data, "data": data}


@router.get(
    "/v1/attention/trends",
    tags=["Attention"],
    summary="Google Trends interest over time + related queries",
)
async def attention_trends(
    keyword: str = Query(..., description="Keyword to measure"),
    timeframe: str = Query(
        "today 12-m", description="Trends timeframe (e.g. 'today 12-m', 'today 3-m', 'now 7-d')"
    ),
) -> dict[str, Any]:
    """Return the interest timeline and related queries for a keyword."""
    mod = _attention_module("trends")
    if mod is None:
        _module_unavailable("trends")
    data = await mod.trend_interest(keyword, timeframe=timeframe)
    return {"success": "error" not in data, "data": data}


@router.get(
    "/v1/attention/ads",
    tags=["Attention"],
    summary="Search the Meta Ad Library for active ads",
)
async def attention_ads(
    page_name: str = Query(..., description="Page name or keyword to search"),
    country: str = Query("US", min_length=2, max_length=2, description="ISO country code"),
    limit: int = Query(20, ge=1, le=200, description="Max ads (default: 20)"),
) -> dict[str, Any]:
    """Return active ads found in the Meta Ad Library."""
    mod = _attention_module("ad_intel")
    if mod is None:
        _module_unavailable("ad_intel")
    data = await mod.search_ads(page_name, country=country, limit=limit)
    return {"success": True, "data": data}


@router.get(
    "/v1/attention/x/posts",
    tags=["Attention"],
    summary="Scrape public X/Twitter posts: profile timeline, status, thread, search",
)
async def attention_x_posts(
    kind: str = Query(
        "profile_timeline",
        description="profile_timeline | status | thread | search",
    ),
    target: str = Query(..., description="Handle, status id/URL, or search query"),
    limit: int = Query(20, ge=1, le=100, description="Max posts (default: 20)"),
) -> dict[str, Any]:
    """Return normalized X posts; a login wall is reported, never fabricated."""
    mod = _attention_module("x_posts")
    if mod is None:
        _module_unavailable("x_posts")
    data = await mod.get_posts(kind, target, limit=limit)
    return {"success": "error" not in data, "data": data}
