# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Adaptive-crawl implementation layer.

Extracted from ``scraping_api`` (thin entrypoint re-exports
``adaptive_crawl``) so the router file holds route wiring only.

``scraping_api`` owns the shared ``logger``/``scraper`` names. They are
read back through the entrypoint at CALL time rather than bound locally, so a
test patching ``scraping_api.scraper`` keeps working — module-attribute
monkeypatching stays effective instead of being frozen into a local at import
time. No back-reference is wired up by the entrypoint, so this module also
imports cleanly on its own.
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import pydantic
from fastapi import Body

if TYPE_CHECKING:
    from types import ModuleType

logger = logging.getLogger(__name__)


def _owner() -> ModuleType:
    """Return the thin entrypoint that owns the shared router names.

    Resolved at call time so this layer never binds a local copy of ``logger``
    or ``scraper`` at import time — patching the entrypoint stays effective.
    """
    return import_module(f"{__name__.rsplit('.', 1)[0]}.scraping_api")


def _warn_page_failed(url: str, error: str) -> None:
    """Record one failed page fetch and skip that page."""
    _owner().logger.warning("adaptive_crawl_page_failed", extra={"url": url, "error": error})


def _warn_map_failed(url: str, error: str) -> None:
    """Record a failed link discovery and skip that URL's expansion."""
    _owner().logger.warning("adaptive_crawl_map_failed", extra={"url": url, "error": error})


def _discover_links(link: str, current_url: str, depth: int, visited: set[str]) -> str | None:
    """Resolve one discovered link to an absolute, not-yet-visited URL."""
    full_url = urljoin(current_url, link)
    if full_url in visited:
        return None
    return full_url


async def adaptive_crawl(
    url: str = Body(...),
    query: str = Body(""),
    max_pages: int = Body(50),
    max_depth: int = Body(3),
    relevance_threshold: float = Body(0.3),
) -> dict[str, Any]:
    """Crawl a website with adaptive stopping.

    Uses information foraging theory to decide when to stop:
    - Stops when content relevance drops below threshold
    - Stops when information gain diminishes
    - Respects max_pages and max_depth limits
    - Ideal for targeted data collection (pricing, docs, products)
    """
    from pry.engine.adaptive import AdaptiveCrawler

    crawler = AdaptiveCrawler(
        max_pages=max_pages,
        max_depth=max_depth,
        relevance_threshold=relevance_threshold,
    )

    pages: list[dict[str, Any]] = []
    to_visit: list[tuple[str, int]] = [(url, 0)]
    visited_urls: set[str] = set()
    owner = _owner()

    while to_visit:
        current_url, depth = to_visit.pop(0)

        if current_url in visited_urls:
            continue
        visited_urls.add(current_url)

        try:
            result = await owner.scraper.scrape(current_url, {"bypass_cloudflare": True})
            content = result.get("content", "") or ""
        except pydantic.ValidationError as e:
            _warn_page_failed(current_url, str(e))
            continue

        decision = await crawler.should_continue(current_url, content, depth, query=query)
        pages.append({"url": current_url, "depth": depth, "decision": decision})

        if not decision["continue"]:
            break

        if depth < max_depth:
            try:
                links = await owner.scraper.map_urls(current_url, {"limit": 10})
            except RuntimeError as e:
                # map_urls raises on a transport failure (direct + flaresolverr
                # both failed) instead of returning an empty "no links" list.
                _warn_map_failed(current_url, str(e))
                continue
            for link in links:
                full_url = _discover_links(link, current_url, depth, visited_urls)
                if full_url is not None:
                    to_visit.append((full_url, depth + 1))

    return {
        "success": True,
        "data": {
            "url": url,
            "query": query,
            "pages": pages,
            "total_pages": len(pages),
            "stats": crawler.get_stats(),
        },
    }
