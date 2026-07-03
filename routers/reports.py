"""Pry — Reports router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse

from errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Reports"])

@router.post(
    "/v1/reports/generate",
    tags=["Reports"],
    summary="Generate a white-label report from scraped data",
)
async def generate_report_endpoint(
    report_type: str = Body(...),
    data: dict[str, Any] = Body(...),
    branding: dict[str, Any] | None = Body(None),
    output_format: str = Body("html"),
) -> dict[str, Any]:
    """Generate a white-label report from scraped data.

    Report types:
    - competitive_analysis: Competitor pricing and activity overview
    - price_monitor: Product price change tracking with visual indicators
    - seo_audit: SEO element analysis with change detection
    - content_tracker: Content change monitoring across pages

    Branding (optional): {"agency_name": "...", "brand_color": "#hex", "logo_url": "..."}
    """
    from reports import generate_report

    result = generate_report(report_type, data, branding, output_format)
    if "error" in result:
        raise InvalidRequestError(result["error"])
    return {"success": True, "data": result}


@router.get("/v1/reports", tags=["Reports"], summary="List generated reports")
async def list_reports_endpoint() -> dict[str, Any]:
    """List all previously generated reports."""
    from reports import list_reports

    reports = list_reports()
    return {"success": True, "data": {"reports": reports, "total": len(reports)}}


@router.get("/v1/report/{report_id}", tags=["Reports"], summary="Get a generated report")
async def get_report(report_id: str) -> Any:
    """Get the HTML content of a generated report."""
    from reports import REPORTS_DIR

    for path in REPORTS_DIR.glob(f"{report_id}_*.html"):
        return HTMLResponse(content=path.read_text())
    raise NotFoundError(f"Report not found: {report_id}")
