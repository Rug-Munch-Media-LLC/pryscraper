"""Pry — detection routes: ``/v1/detect-block`` and ``/v1/capture/lazy``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from pry.api.routers.scraping.seams import bindings
from pry.core.observability import track_scrape
from pry.engine.scraping_service import (
    detect_block as detect_block_service,
    detect_lazy_content as detect_lazy_service,
)

router = APIRouter()


@router.post("/v1/detect-block", summary="Detect if a site is blocking the scraper")
async def detect_block(url: str = Body(...)) -> dict[str, Any]:
    """Detect anti-bot protection (tier, vendor, confidence)."""
    return await detect_block_service(url, bindings().get_client)


@router.post("/v1/capture/lazy", summary="Detect and handle lazy-loaded content")
async def detect_lazy_content(
    url: str = Body(...), auto_scroll: bool = Body(True), max_scrolls: int = Body(5)
) -> dict[str, Any]:
    """Detect lazy loading and optionally generate auto-scroll JS."""
    ctx = bindings()
    with track_scrape(method="lazy"):
        data = await detect_lazy_service(
            url,
            scraper=ctx.scraper,
            get_client=ctx.get_client,
            auto_scroll=auto_scroll,
            max_scrolls=max_scrolls,
        )
    return {"success": True, "data": data}
