"""Pry — Scraping router composition (scrape, crawl, batch, detect).

Route bodies live in the per-resource modules (``scrape_routes``,
``crawl_map_routes``, ``batch_routes``, ``detect_routes``). This module owns the
shared bindings the routes resolve at call time — ``scraper``, ``cache``,
``extractor``, ``queue``, ``get_client`` — and assembles the single ``router``
that the API mounts. Keeping the bindings here also keeps the established test
seam (``pry.api.routers.scraping.scraping.scraper``) working.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from fastapi import APIRouter

from pry.api.client import get_client
from pry.api.routers.scraping import (
    batch_routes,
    crawl_map_routes,
    detect_routes,
    scrape_routes,
)
from pry.api.routers.scraping.scraping_models import CrawlRequest, MapRequest, ScrapeRequest
from pry.core.deps import cache, extractor, queue, scraper

router = APIRouter(tags=["Scraping"])
router.include_router(scrape_routes.router)
router.include_router(crawl_map_routes.router)
router.include_router(batch_routes.router)
router.include_router(detect_routes.router)

# Re-exported on purpose: route modules resolve these through ``seams.bindings``
# at call time, and the test suite patches them here.
__all__ = [
    "CrawlRequest",
    "MapRequest",
    "ScrapeRequest",
    "cache",
    "extractor",
    "get_client",
    "queue",
    "router",
    "scraper",
]
