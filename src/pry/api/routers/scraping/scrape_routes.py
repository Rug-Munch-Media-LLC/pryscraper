"""Pry — ``POST /v1/scrape`` (single URL, Firecrawl-compatible formats).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import copy
from functools import partial
from typing import Any

from fastapi import APIRouter, Request

from pry.api.routers.scraping.http_guards import audit_http, deny_if_blocked
from pry.api.routers.scraping.media_formats import MEDIA_FORMATS, media_extras
from pry.api.routers.scraping.scraping_models import ScrapeRequest  # noqa: TC001 - runtime
from pry.api.routers.scraping.seams import bindings
from pry.core.errors import ExternalServiceError, PryError, ScrapeError
from pry.core.observability import track_scrape
from pry.engine.scraping_service import format_extras, render_media_for, requested_formats

router = APIRouter()


async def _scrape_fresh(
    request: ScrapeRequest, requested: set[str], *, scraper: Any, extractor: Any
) -> dict[str, Any]:
    """Run one scrape and shape the Firecrawl-compatible response body."""
    result = await scraper.scrape(
        request.url,
        {
            "timeout": request.timeout,
            "bypass_cloudflare": request.bypassCloudflare,
            "js_render": request.jsRender,
            "formats": request.formats,
        },
    )
    if result.get("status") != "ok":
        raise ScrapeError(
            result.get("error", "Scrape failed"),
            verdict=result.get("verdict"),
            tiers_attempted=result.get("tiers_attempted"),
            tiers_failed=result.get("tiers_failed"),
        )
    content = result.get("content", "")
    data: dict[str, Any] = {
        "markdown": content,
        "metadata": {
            "url": request.url,
            "method": result.get("method", "unknown"),
            "title": result.get("title", ""),
            "description": result.get("description", ""),
            "markdown_quality": result.get("markdown_quality", 0),
            "formats": sorted(requested),
        },
    }
    data.update(format_extras(requested, result.get("raw_html", ""), request.url))
    data.update(
        await media_extras(
            requested, request.url, partial(render_media_for, scraper), request.timeout
        )
    )
    response: dict[str, Any] = {"success": True, "data": data}
    if request.jsonSchema:
        response["data"]["json"] = await extractor.extract(content, request.jsonSchema)
    return response


def _cache_options(request: ScrapeRequest, requested: set[str]) -> dict[str, Any]:
    """Cache identity: a markdown-only entry must not serve an html caller."""
    return {
        "bypass_cloudflare": request.bypassCloudflare,
        "js_render": request.jsRender,
        "formats": ",".join(sorted(requested)),
    }


def _paginate(response: dict[str, Any], offset: int, limit: int) -> dict[str, Any]:
    """Apply the offset/limit window to a scrape response in place."""
    markdown = response.get("data", {}).get("markdown", "")
    response["data"]["markdown"] = markdown[offset : offset + limit]
    response["data"]["metadata"]["offset"] = offset
    response["data"]["metadata"]["total"] = len(markdown)
    return response


@router.post("/v1/scrape", summary="Scrape a single URL")
async def scrape(request: ScrapeRequest, http_request: Request) -> dict[str, Any]:
    """Scrape a URL. Auto-bypasses Cloudflare. Returns markdown or JSON."""
    deny_if_blocked(http_request, "scrape", request.url)
    requested = requested_formats(request.formats)
    ctx = bindings()
    opts = _cache_options(request, requested)
    # Base64 screenshot/PDF payloads can be megabytes; never put them in the
    # shared response cache.
    media = bool(requested & MEDIA_FORMATS)
    cached = None if media else ctx.cache.get(request.url, opts)
    if cached:
        out = _paginate(copy.deepcopy(cached), request.offset, request.limit)
        out["_cached"] = True
        audit_http(http_request, "scrape", request.url, "success")
        return out
    try:
        with track_scrape(method="direct"):
            response = await _scrape_fresh(
                request, requested, scraper=ctx.scraper, extractor=ctx.extractor
            )
        if not media:
            ctx.cache.set(request.url, response, opts)
        out = _paginate(copy.deepcopy(response), request.offset, request.limit)
        audit_http(http_request, "scrape", request.url, "success")
        return out
    except PryError:
        audit_http(http_request, "scrape", request.url, "error")
        raise
    except Exception as e:
        audit_http(http_request, "scrape", request.url, "error")
        raise ExternalServiceError(str(e)) from e
