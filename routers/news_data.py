"""Pry — news headlines + sentiment data router.

Exposes real-time news headlines, article extraction, aggregate sentiment
and per-day entity timelines backed by the ``news_data`` subpackage (built
in parallel, so every import is guarded and degrades to 502 while a module
has not landed yet). Data sources are free and no-auth (GDELT DOC 2.0 API +
RSS fallback) — ideal for trading/PR headline feeds.

Endpoints:
- GET /v1/news/headlines  — recent headlines matching a query
- GET /v1/news/article    — full article extraction (text + summary)
- GET /v1/news/sentiment  — aggregate sentiment for a query
- GET /v1/news/timeline   — per-day entity timeline (tone + top sources)

This router is NOT wired into api.py yet (the lead wires new routers after
the parallel build lands). It is import-safe standalone.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import logging
from typing import Any, NoReturn

from fastapi import APIRouter, Query

from pry.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["News Data"])


def _news_module() -> Any:
    """Import the ``news_data`` package with a guarded ImportError.

    The package is created in parallel by another agent; return None when it
    has not landed yet so callers can degrade gracefully.
    """
    try:
        return importlib.import_module("news_data")
    except ImportError:
        logger.warning("news_data_module_unavailable")
        return None


def _module_unavailable() -> NoReturn:
    raise ExternalServiceError("news_data is not available yet (parallel build in progress)")


@router.get(
    "/v1/news/headlines",
    tags=["News Data"],
    summary="Recent headlines matching a query (GDELT + RSS)",
)
async def news_headlines(
    query: str = Query(..., min_length=1, max_length=500, description="Search term"),
    limit: int = Query(20, ge=1, le=250, description="Max headlines (default: 20)"),
    timeframe: str = Query("24h", max_length=20, description="GDELT timespan (e.g. 24h, 7d)"),
) -> dict[str, Any]:
    """Fetch recent headlines. Returns a list of headline records."""
    mod = _news_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_headlines(query, limit=limit, timeframe=timeframe)
    return {"success": True, "data": data, "query": query, "limit": limit, "timeframe": timeframe}


@router.get(
    "/v1/news/article",
    tags=["News Data"],
    summary="Extract a full article (text + summary + metadata)",
)
async def news_article(
    url: str = Query(..., min_length=8, max_length=2000, description="Article URL"),
) -> dict[str, Any]:
    """Extract one article via Pry's scraper. Returns {} when extraction fails."""
    mod = _news_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_article(url)
    return {"success": True, "data": data, "url": url}


@router.get(
    "/v1/news/sentiment",
    tags=["News Data"],
    summary="Aggregate sentiment for a query (GDELT tone + keyword fallback)",
)
async def news_sentiment(
    query: str = Query(..., min_length=1, max_length=500, description="Search term"),
    timeframe: str = Query("24h", max_length=20, description="GDELT timespan (e.g. 24h, 7d)"),
    limit: int = Query(20, ge=1, le=250, description="Max articles for the aggregate"),
) -> dict[str, Any]:
    """Fetch sentiment aggregates: avg_tone, positive/negative pct, timeline."""
    mod = _news_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_sentiment(query, timeframe=timeframe, limit=limit)
    return {"success": True, "data": data, "query": query, "timeframe": timeframe}


@router.get(
    "/v1/news/timeline",
    tags=["News Data"],
    summary="Per-day entity timeline with tone + top sources",
)
async def news_timeline(
    entity: str = Query(..., min_length=1, max_length=500, description="Entity / search term"),
    timeframe: str = Query("7d", max_length=20, description="GDELT timespan (default: 7d)"),
    limit: int = Query(20, ge=1, le=250, description="Max articles to pull"),
) -> dict[str, Any]:
    """Fetch a per-day timeline for an entity. Returns a list of day records."""
    mod = _news_module()
    if mod is None:
        _module_unavailable()
    data = await mod.get_entity_timeline(entity, timeframe=timeframe, limit=limit)
    return {"success": True, "data": data, "entity": entity, "timeframe": timeframe}
