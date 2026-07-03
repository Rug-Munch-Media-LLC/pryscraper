"""Pry — Enrichment router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Enrichment"])

@router.post(
    "/v1/enrich",
    tags=["Enrichment"],
    summary="Enrich scraped data with company info, tech stack, social profiles",
)
async def enrich_data(
    url: str = Body(...),
    include_tech_stack: bool = Body(True),
    include_social: bool = Body(True),
    include_company: bool = Body(True),
) -> dict[str, Any]:
    """Enrich a URL with supplemental business intelligence.

    Returns:
    - Tech stack detection (CMS, framework, CDN, analytics, payments)
    - Social media profiles (Twitter, LinkedIn, Facebook, Instagram, GitHub, etc.)
    - Company information (email, phone, address, founded year, team size)
    """
    from enrichment import enrich_url

    result = await enrich_url(url)
    filtered: dict[str, Any] = {"url": url}
    if include_tech_stack:
        filtered["tech_stack"] = result.get("tech_stack")
    if include_social:
        filtered["social_profiles"] = result.get("social_profiles")
    if include_company:
        filtered["company_info"] = result.get("company_info")

    return {"success": True, "data": filtered}


@router.post(
    "/v1/enrich/tech-stack", tags=["Enrichment"], summary="Detect technologies used on a website"
)
async def detect_tech(url: str = Body(...)) -> dict[str, Any]:
    """Detect what technologies a website is built with.

    Detects: CMS (WordPress, Shopify, Wix), frameworks (Next.js, Django, Rails),
    frontend (React, Vue, Angular), CDN (Cloudflare, Fastly), analytics (GA, Hotjar),
    payments (Stripe, PayPal).
    """
    from enrichment import enrich_url

    result = await enrich_url(url)
    return {"success": True, "data": result.get("tech_stack", {})}
