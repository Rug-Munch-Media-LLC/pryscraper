"""Pry — Structure router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from pry.core.errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Structure"])


@router.post(
    "/v1/structure/check",
    tags=["Structure"],
    summary="Check if CSS selectors still match on a page",
)
async def structure_check(
    url: str = Body(...),
    selectors: list[dict[str, Any]] = Body(...),
) -> dict[str, Any]:
    """Check if CSS selectors still match on a page.

    Use this to verify your scraper templates still work after
    a site redesign. Returns per-selector match status.

    Selectors format: [{"name": "title", "selector": "h1", "type": "css"}]
    """
    from pry.actors.structure_monitor import check_selectors

    result = await check_selectors(url, selectors)
    return {"success": "error" not in result, "data": result}


@router.post(
    "/v1/structure/monitor", tags=["Structure"], summary="Monitor page structure changes over time"
)
async def structure_monitor(
    url: str = Body(...),
    selectors: list[dict[str, Any]] = Body(...),
    template_id: str = Body(""),
) -> dict[str, Any]:
    """Monitor page structure changes and detect broken selectors.

    Compares current selector match status to previous checks.
    Alerts when selectors stop matching (site redesign detected).

    Use this as a pre-scrape health check for your templates.
    """
    from pry.actors.structure_monitor import monitor_page_structure

    result = await monitor_page_structure(url, selectors, template_id)
    return {"success": "error" not in result, "data": result}


@router.post(
    "/v1/structure/check-template",
    tags=["Structure"],
    summary="Verify a scraper template still works",
)
async def structure_check_template(
    template_id: str = Body(...), url: str = Body("")
) -> dict[str, Any]:
    """Check if a pre-built scraper template still works against a URL.

    Extracts the template's selectors and checks each one.
    If selectors fail, the template needs updating.
    """
    from pry.actors.structure_monitor import monitor_page_structure
    from pry.commerce.template_engine import get_template

    template = get_template(template_id)
    if not template:
        raise NotFoundError(f"Template not found: {template_id}")

    schema = template.get("schema", {})
    fields = schema.get("fields", [])
    selectors = [
        {
            "name": f.get("name", f"field_{i}"),
            "selector": f.get("selector", ""),
            "type": "css" if f.get("type") != "xpath" else "xpath",
        }
        for i, f in enumerate(fields)
        if f.get("selector")
    ]

    if not selectors:
        raise InvalidRequestError("Template has no selectable fields")

    # If no URL provided, try the template's site URL
    if not url:
        site = template.get("site", "")
        url = (
            f"https://www.{site}"
            if site and not site.startswith("http")
            else (site if site else "https://example.com")
        )

    result = await monitor_page_structure(url, selectors, template_id)
    return {"success": "error" not in result, "data": result}
