"""Pry — Parsing router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body
from pydantic import BaseModel

from pry.api.client import get_client
from pry.core.deps import parser, scraper
from pry.core.errors import ExternalServiceError, PryError, ScrapeError
from pry.engine.fetch_guard import guard_get

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Parsing"])


@router.post(
    "/v1/parse", tags=["Parsing"], summary="Parse a document (PDF, DOCX, image, CSV, JSON)"
)
async def parse_document(request: ParseRequest) -> dict[str, Any]:
    """Parse a document (PDF, DOCX, image, CSV, JSON) to text."""
    try:
        result = await parser.parse(request.url, request.timeout or 60)
        return {"success": True, "data": result}
    except PryError:
        raise
    except Exception as e:
        raise ExternalServiceError(str(e)) from e


@router.post(
    "/v1/markdown", tags=["Parsing"], summary="Generate markdown with content filtering strategies"
)
async def generate_markdown(
    url: str = Body(...),
    mode: str = Body("raw"),
    query: str = Body(""),
    threshold: float = Body(0.3),
) -> dict[str, Any]:
    """Generate markdown with configurable content filtering.

    Modes:
    - raw: Unfiltered markdown
    - fit: Prune boilerplate (nav, ads, footers)
    - bm25: Filter by BM25 relevance to query (requires query param)
    """
    from pry.engine.markdown_gen import (
        BM25ContentFilter,
        DefaultMarkdownGenerator,
        PruningContentFilter,
    )

    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    content = result.get("content", "")
    if not content:
        raise ScrapeError("No content scraped")

    if mode == "fit":
        filter_strategy: PruningContentFilter | BM25ContentFilter | None = PruningContentFilter(
            threshold=threshold
        )
    elif mode == "bm25":
        if not query:
            filter_strategy = PruningContentFilter(threshold=threshold)
        else:
            filter_strategy = BM25ContentFilter(threshold=threshold)
    else:
        filter_strategy = None

    gen = DefaultMarkdownGenerator(content_filter=filter_strategy)
    md_result = gen.generate(content, url=url, query=query)

    return {
        "success": True,
        "data": md_result,
    }


@router.post("/v1/shadow-dom", tags=["Parsing"], summary="Extract content from Shadow DOM")
async def extract_shadow_dom(
    url: str = Body(...),
    flatten: bool = Body(True),
) -> dict[str, Any]:
    """Scrape a page and extract content from Shadow DOM components.

    Useful for modern web apps built with Lit, web components, or
    frameworks that use Shadow DOM encapsulation.
    """
    from pry.engine.shadow_dom import ShadowDOMProcessor, has_shadow_dom

    result = await scraper.scrape(url, {"bypass_cloudflare": True, "js_render": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    html = result.get("raw_html", "")
    if not html:
        # Try to get via direct fetch
        client = await get_client()
        try:
            resp = await guard_get(client, url, timeout=30)
            html = resp.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            raise ScrapeError("Could not fetch raw HTML") from e

    shadow_present = has_shadow_dom(html)
    flat_html = ""

    if shadow_present and flatten:
        processor = ShadowDOMProcessor()
        flat_html = processor.process(html)

    return {
        "success": True,
        "data": {
            "url": url,
            "shadow_dom_detected": shadow_present,
            "flattened": bool(flat_html),
            "content": flat_html[:10000] if flat_html else html[:10000],
            "raw_html_length": len(html),
            "flat_html_length": len(flat_html) if flat_html else len(html),
        },
    }


class ParseRequest(BaseModel):
    url: str
    timeout: int | None = 60
