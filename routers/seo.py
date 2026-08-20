"""Pry — SEO router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SEO"])


@router.post("/v1/seo/analyze", tags=["SEO"], summary="Analyze SEO elements from a URL")
async def seo_analyze(url: str = Body(...)) -> dict[str, Any]:
    """Analyze all SEO elements from a URL.

    Returns: title, meta description, keywords, headings (H1/H2),
    canonical, OG tags, Twitter cards, word count, link counts,
    schema markup, hreflang tags.
    """
    from seo_monitor import analyze_seo

    result = await analyze_seo(url)
    return {"success": "error" not in result, "data": result}


@router.post("/v1/seo/track", tags=["SEO"], summary="Track SEO changes since last scan")
async def seo_track(url: str = Body(...)) -> dict[str, Any]:
    """Track SEO changes since the last scan of this URL.

    Compares current SEO elements to previous snapshot and reports
    what changed (title, description, headings, etc.).
    """
    from seo_monitor import track_seo_changes

    result = await track_seo_changes(url)
    return {"success": "error" not in result, "data": result}


@router.post("/v1/seo/keywords", tags=["SEO"], summary="Analyze keyword presence in URL content")
async def seo_keywords(
    url: str = Body(...),
    keywords: list[str] = Body(...),
) -> dict[str, Any]:
    """Analyze which keywords a URL targets.

    Checks each keyword for:
    - Presence in title tag
    - Presence in H1 headings
    - Presence in meta description
    - Frequency in body content
    - Keyword density percentage
    """
    from seo_monitor import get_seo_keyword_insights

    result = await get_seo_keyword_insights(url, keywords)
    return {"success": "error" not in result, "data": result}
