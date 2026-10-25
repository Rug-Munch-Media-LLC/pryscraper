"""Pry Apify Actor — web scraping + browser automation on the Apify platform.

Runs Pry's multi-tier scraper (UltimateScraper) as an Apify actor.
Accepts a list of URLs, scrapes each one through up to 12 fallback tiers,
and pushes the results (markdown content + metadata) to the Apify dataset.

Usage:
    Deploy to Apify Console or run locally with:
        apify run -p

Input (JSON):
    {
        "urls": ["https://example.com", ...],
        "max_pages": 1,
        "timeout": 30,
        "output_format": "markdown",
        "proxy_config": {
            "use_apify_proxies": true,
            "proxy_country": "US"
        }
    }

Output (dataset items):
    {
        "url": "https://example.com",
        "status": "ok" | "error",
        "content": "...markdown or html...",
        "method": "direct" | "flaresolverr" | ...,
        "metadata": {
            "title": "...",
            "description": "...",
            "domain": "example.com",
            "scraped_at": "2026-07-03T..."
        }
    }

Import path is unchanged: callers and ``.actor/src/main.py`` keep importing
from ``pry.actors.apify_actor``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry.actors.apify_actor.links import _extract_links
from pry.actors.apify_actor.models import (
    ApifyActorInput,
    ApifyActorOutput,
    ApifyProxyConfig,
    ApifyScrapeMetadata,
)
from pry.actors.apify_actor.options import build_base_options
from pry.actors.apify_actor.push import _push_with_retry
from pry.actors.apify_actor.runner import main
from pry.actors.apify_actor.scrape import scrape_url

__all__ = [
    "ApifyActorInput",
    "ApifyActorOutput",
    "ApifyProxyConfig",
    "ApifyScrapeMetadata",
    "_extract_links",
    "_push_with_retry",
    "build_base_options",
    "main",
    "scrape_url",
]
