"""Pry — Compliance router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Compliance"])


@router.post(
    "/v1/compliance/check", tags=["Compliance"], summary="Run full compliance check on a URL"
)
async def compliance_check(url: str = Body(...)) -> dict[str, Any]:
    """Run a full legal compliance check on a target URL.

    Analyzes:
    - robots.txt crawl permissions
    - Terms of Service classification (restrictive/permissive/moderate)
    - Jurisdiction detection (GDPR, CCPA, LGPD)
    - Sensitive data detection (PII, financial, health, contact)

    Returns a green/yellow/red risk score with recommendations.
    """
    from compliance import run_compliance_check

    result = await run_compliance_check(url)
    return {"success": True, "data": result}


@router.get(
    "/v1/compliance/check", tags=["Compliance"], summary="Get compliance check documentation"
)
async def compliance_docs() -> dict[str, Any]:
    """Get information about the compliance check endpoint."""
    return {
        "success": True,
        "data": {
            "description": "Legal compliance engine for web scraping targets",
            "risk_levels": {
                "green": "Low risk — standard scraping practices",
                "yellow": "Moderate risk — proceed with caution",
                "red": "High risk — legal review required",
            },
            "factors_checked": [
                "robots.txt crawl permissions",
                "Terms of Service classification",
                "Jurisdiction detection (GDPR/CCPA/LGPD)",
                "Sensitive data categories (PII, financial, health, contact)",
            ],
        },
    }
