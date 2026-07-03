"""Pry — Referrals router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Referrals"])

@router.get(
    "/v1/referrals/catalog",
    tags=["Referrals"],
    summary="Get all available referral/affiliate programs",
)
async def get_referral_catalog(category: str = "") -> dict[str, Any]:
    """List all referral programs Pry supports.

    60+ providers across categories: LLM, hosting, domains, CDN, email,
    monitoring, proxies, voice, media, devtools, search, CAPTCHA.
    """
    from referrals import ReferralTracker

    return {"success": True, "data": ReferralTracker().get_catalog(category)}


@router.get(
    "/v1/referrals/stats", tags=["Referrals"], summary="Get referral click and conversion stats"
)
async def get_referral_stats(days_back: int = 30) -> dict[str, Any]:
    """Get referral tracking statistics for the last N days."""
    from referrals import ReferralTracker

    return {"success": True, "data": ReferralTracker().get_stats(days_back)}


@router.post("/v1/referrals/click", tags=["Referrals"], summary="Record a referral link click")
async def record_referral_click(
    provider_tag: str = Body(...),
    source: str = Body("api"),
    user_id: str = Body(""),
) -> dict[str, Any]:
    """Record when a user clicks a referral link. Returns tracking ID."""
    from referrals import PROVIDER_CATALOG, ReferralTracker

    url = ""
    for _cat, providers in PROVIDER_CATALOG.items():
        for p in providers:
            if p.get("tag") == provider_tag:
                url = p["url"]
                break
        if url:
            break
    if not url:
        return {"success": False, "error": f"Unknown provider: {provider_tag}"}
    click_id = ReferralTracker().record_click(provider_tag, url, source, user_id)
    return {"success": True, "data": {"click_id": click_id, "url": url}}


@router.post("/v1/referrals/convert", tags=["Referrals"], summary="Record a referral conversion")
async def record_referral_conversion(
    click_id: str = Body(...),
    revenue_usd: float = Body(0.0),
    notes: str = Body(""),
) -> dict[str, Any]:
    """Record that a referral click resulted in a conversion."""
    from referrals import ReferralTracker

    success = ReferralTracker().record_conversion(click_id, revenue_usd, notes)
    return {"success": success}
