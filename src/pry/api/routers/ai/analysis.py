"""Pry — Analysis router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, Body

from pry.api.client import get_client
from pry.api.routers.scraping.fetch import guard_get
from pry.core.deps import advanced, scraper
from pry.core.errors import ScrapeError
from pry.core.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Analysis"])


@router.post("/v1/compare", tags=["Analysis"], summary="Compare content of two URLs")
async def compare(url1: str = Body(...), url2: str = Body(...)) -> dict[str, Any]:
    """Scrape two URLs and compare their content. Shows additions, deletions, changes."""
    r1, r2 = await asyncio.gather(scraper.scrape(url1), scraper.scrape(url2))
    c1, c2 = r1.get("content", ""), r2.get("content", "")
    diff = list(
        difflib.unified_diff(
            c1.splitlines(keepends=True),
            c2.splitlines(keepends=True),
            fromfile=url1,
            tofile=url2,
            n=3,
        )
    )
    return {
        "success": True,
        "data": {
            "url1": url1,
            "url2": url2,
            "diff": diff[:200],
            "changes": len(diff),
            "identical": len(diff) == 0,
        },
    }


@router.post("/v1/watch", tags=["Analysis"], summary="Watch a page for changes")
async def watch_page(
    url: str = Body(...), webhook: str = Body(...), interval: int = 3600, selector: str = ""
) -> dict[str, Any]:
    """Watch a page for changes. Accepts a webhook URL for notification.
    First call registers the watch, subsequent calls compare and notify.
    Firecrawl charges $99/mo for this feature."""
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError("Could not scrape URL")
    content = result.get("content", "")
    diff_result = await advanced.track_diff(url, content)
    # Fire webhook asynchronously on first registration (webhook support)
    if webhook and diff_result["status"] == "registered":
        _schedule_watch_webhook(webhook, url, diff_result)
    return {
        "success": True,
        "data": {
            "url": url,
            "status": diff_result["status"],
            "version": diff_result["version"],
            "webhook": webhook,
            "interval": interval,
            "message": "Page registered for change tracking.",
        },
    }


@router.post("/v1/summarize", tags=["Analysis"], summary="AI summarize scraped content")
async def summarize(url: str = Body(...), max_words: int = 100) -> dict[str, Any]:
    """Scrape + AI summarize using local Ollama. Free, private."""
    result = await scraper.scrape(url, {"bypass_cloudflare": True, "timeout": 30})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error", "Scrape failed"))
    summary = await advanced.summarize(result.get("content", ""), max_words)
    return {"success": True, "data": {"url": url, **summary}}


@router.post("/v1/diff", tags=["Analysis"], summary="Track page changes over time")
async def diff(url: str = Body(...), content: str | None = Body(None)) -> dict[str, Any]:
    """Track page changes over time. Returns diff from last scrape."""
    if content:
        diff_result = await advanced.track_diff(url, content)
    else:
        result = await scraper.scrape(url)
        if result.get("status") != "ok":
            raise ScrapeError("Could not scrape URL")
        diff_result = await advanced.track_diff(url, result.get("content", ""))
    return {"success": True, "data": diff_result}


@router.post("/v1/categorize", tags=["Analysis"], summary="AI-categorize scraped content")
async def categorize(url: str = Body(...)) -> dict[str, Any]:
    """AI-categorize scraped content into topic tags."""
    result = await scraper.scrape(url)
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Categorize failed")
    tags = await advanced.categorize(result.get("content", ""))
    kw = advanced.keyword_density(result.get("content", ""))
    readability = advanced.readability(result.get("content", ""))
    return {
        "success": True,
        "data": {"url": url, "tags": tags, "keywords": kw[:10], "readability": readability},
    }


@router.post("/v1/suggest", tags=["Analysis"], summary="AI-suggest schema fields for a URL")
async def suggest_schema(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Suggest CSS selectors for a page's price/name/image/etc. fields.

    ``url`` comes straight from the request body, so the raw-HTML pass goes
    through :func:`guard_get` — the URL is validated and every redirect hop is
    re-validated, which a bare ``client.get`` does not do — and it runs BEFORE
    the scraper, so a rejected target is refused (HTTP 400) before any layer
    opens a connection to it.

    A transport failure is different: the page may simply be unreachable, and the
    route still answers with the scraper's own text plus ``html_error`` naming
    the reason, so absent candidates are never silently attributed to the page.
    """
    url = data.get("url", "")

    html, html_error = await _fetch_page_html(url)
    result = await scraper.scrape(url, {"bypass_cloudflare": True, "timeout": 30})
    content = result.get("content", "")
    schema = {"_page_title": result.get("title", "")}
    candidates: dict[str, str] = {}
    for pattern, field in [
        (r'["\']((?:price|cost|amount)[^"\']*)["\']', "price"),
        (r'["\'](product-title|product-name|item-name)[^"\']*["\']', "name"),
        (r'["\'](?:product-image|main-image|featured-image)[^"\']*["\']', "image"),
        (r'["\'](?:description|product-desc|item-desc)[^"\']*["\']', "description"),
        (r'["\'](?:rating|stars|review-score)[^"\']*["\']', "rating"),
        (r'["\'](?:stock|availability|status)[^"\']*["\']', "stock"),
    ]:
        found = re.findall(pattern, html.lower())
        if found:
            candidates[field] = f'[class*="{found[0][:15]}"]'
    if "name" not in candidates:
        h1 = re.findall(r'<h1[^>]*class=["\']([^"\']*)["\']', html)
        if h1:
            candidates["name"] = f"h1.{h1[0].replace(' ', '.')}"
    schema["suggested"] = candidates
    if html_error is not None:
        schema["html_error"] = html_error
    if content and len(content) > 200:
        await _add_llm_suggestions(schema, content)
    return {"success": True, "data": schema}


async def _fetch_page_html(url: str) -> tuple[str, str | None]:
    """Fetch a page's raw HTML through the SSRF guard.

    Returns ``(html, error)``.

    Raises:
        InvalidRequestError: Propagated from the guard when the URL (or a
            redirect it returns) is internal. The route must NOT swallow this
            into the error string: the guard's exception is a ``PryError`` with
            ``status_code`` 400, so letting it propagate is what turns a blocked
            URL into a 4xx instead of a 500.
    """
    try:
        client = await get_client()
        resp = await guard_get(client, url, timeout=15)
    except httpx.HTTPError as e:
        # Transport-only failure: the URL was safe, the host was not reachable.
        error = f"{type(e).__name__}: {e}"[:300]
        logger.warning("suggest_schema_fetch_failed", extra={"url": url, "error": error})
        return "", error
    return resp.text, None


async def _add_llm_suggestions(schema: dict[str, Any], content: str) -> None:
    """Merge the local model's selector suggestions into ``schema`` in place."""
    try:
        client = await get_client()
        resp = await client.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": "qwen2.5-coder:3b",
                "prompt": (
                    "Analyze this page. Return ONLY JSON with field names as keys and"
                    " CSS selectors as values. Look for: price, name, description,"
                    " image, rating, stock.\n\n" + content[:4000]
                ),
                "stream": False,
                "options": {"num_ctx": 8192, "temperature": 0.1},
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return
        m = re.search(r"\{.*\}", resp.json().get("response", ""), re.S)
        if not m:
            return
        try:
            llm = json.loads(m.group(0))
        except json.JSONDecodeError:
            logger.warning("llm_schema_parse_failed")
            return
        if isinstance(llm, dict):
            schema["llm_suggested"] = llm
    except httpx.HTTPError:
        # settings.ollama_url is server configuration, not caller input.
        logger.warning("ollama_suggest_schema_failed")


# The watch-webhook delivery path (SSRF-guarded fire-and-forget POST plus the
# done-callback that makes its outcome observable) lives in
# pry.api.routers.ai._watch_webhook. It is re-exported here because these are the
# names analysis.py has always exposed -- callers and the regression tests bind
# to them on THIS module (the scheduler test swaps ``_fire_watch_webhook`` out on
# this module), and the scheduler looks ``_fire_watch_webhook`` up here at call
# time, so the binding must stay a real attribute of this module.
from pry.api.routers.ai._watch_webhook import (  # noqa: E402,F401 -- public re-export
    _fire_watch_webhook,
    _log_watch_webhook_outcome,
    _schedule_watch_webhook,
)
