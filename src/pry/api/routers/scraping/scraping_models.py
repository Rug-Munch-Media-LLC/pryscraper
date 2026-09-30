"""Pry — request models for the scraping router.

Split from `scraping.py` on 2026-09-30 so the request SCHEMA (and the budget
rationale that lives on it) is editable without touching endpoint bodies.

Pure code move: same field names, same types, same defaults, same order. Every
model is re-exported from `pry.api.routers.scraping.scraping`, so existing
import paths and the OpenAPI component names (`ScrapeRequest`, `CrawlRequest`,
`MapRequest`) are unchanged.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = ["CrawlRequest", "MapRequest", "ScrapeRequest"]


class ScrapeRequest(BaseModel):
    url: str
    formats: list[str] | None = None
    onlyMainContent: bool | None = True
    # 2026-08-29 — was 30, which is shorter than the chain this field budgets.
    #
    # The tier chain runs up to ten attempts (direct, tls_fingerprint,
    # cloudscraper, flaresolverr, undetected, camoufox, playwright, googlebot,
    # tor, premium_proxy, archive, google_cache) at up to 45s each. A 30s
    # request budget therefore expires part-way down the chain, and the error
    # reports whichever tier happened to be in flight — which is usually
    # `premium_proxy`, the LAST paid rung. The result is a false "blocked"
    # verdict that names the most expensive tier, so the natural reading is
    # "the proxy is broken" and the real cause is the budget.
    #
    # Measured on one site: direct curl with a browser UA returned 200 with
    # 40,859 bytes of real content; this API at 30 returned
    # `premium_proxy_failed`; at 100 it returned 3,784 characters in 41s served
    # by the `archive` tier. The proxy was never the problem and was never
    # reached.
    #
    # 120s is long enough for the chain to finish and short enough to stay
    # inside a typical client or proxy read timeout. Callers with a tighter
    # budget can still pass an explicit value; this only fixes the default that
    # silently manufactured failures.
    timeout: int | None = 120
    bypassCloudflare: bool | None = True
    jsRender: bool | None = False
    jsonSchema: dict[str, str] | None = None
    # Window into the extracted markdown (for paging very large bodies).
    offset: int = 0
    limit: int = 100000


class CrawlRequest(BaseModel):
    url: str
    maxPages: int | None = 10
    maxDepth: int | None = 2
    scrapeOptions: dict[str, Any] | None = None
    webhook: str | None = None


class MapRequest(BaseModel):
    url: str
    search: str | None = None
    ignoreSitemap: bool | None = True
    limit: int | None = 50
