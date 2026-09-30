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
import urllib.parse
from typing import Any

import httpx
from fastapi import APIRouter, Body

from pry.api.client import get_client
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
    url = data.get("url", "")

    result = await scraper.scrape(url, {"bypass_cloudflare": True, "timeout": 30})
    content = result.get("content", "")
    html = ""
    try:
        client = await get_client()
        resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
        html = resp.text
    except httpx.HTTPError:
        logger.warning("suggest_schema_fetch_failed", extra={"url": url})
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
    if content and len(content) > 200:
        try:
            prompt = (
                "Analyze this page. Return ONLY JSON with field names as keys and CSS selectors as values. Look for: price, name, description, image, rating, stock.\n\n"
                + content[:4000]
            )
            client = await get_client()
            ollama_url = settings.ollama_url
            resp = await client.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": "qwen2.5-coder:3b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_ctx": 8192, "temperature": 0.1},
                },
                timeout=30,
            )
            if resp.status_code == 200:
                llm_raw = resp.json().get("response", "")
                llm_match = re.search(r"\{.*\}", llm_raw, re.S)
                if llm_match:
                    try:
                        llm = json.loads(llm_match.group(0))
                        if isinstance(llm, dict):
                            schema["llm_suggested"] = llm
                    except json.JSONDecodeError:
                        logger.warning("llm_schema_parse_failed")
        except httpx.HTTPError:
            logger.warning("ollama_suggest_schema_failed")
    return {"success": True, "data": schema}


def _schedule_watch_webhook(
    webhook: str, url: str, diff_result: dict[str, Any]
) -> asyncio.Task[None]:
    """Start the fire-and-forget watch webhook and make its outcome observable.

    ``asyncio.create_task`` attaches no done-callback, so an exception escaping
    the coroutine is swallowed silently — the request still returns 200 and the
    delivery failure is invisible. We register a done-callback that logs the
    outcome and retrieves the exception so asyncio does not report it as an
    unhandled task exception.

    Returns:
        The scheduled task, so callers and tests can await it.
    """
    task = asyncio.create_task(_fire_watch_webhook(webhook, url, diff_result))
    task.add_done_callback(_log_watch_webhook_outcome)
    return task


def _log_watch_webhook_outcome(task: asyncio.Task[None]) -> None:
    """Log a completed watch-webhook task. Never logs the response body."""
    if task.cancelled():
        logger.info("watch_webhook_cancelled")
        return
    error = task.exception()
    if error is not None:
        logger.warning(
            "watch_webhook_task_failed",
            extra={"url": task.get_name(), "error_type": type(error).__name__},
        )
        return
    logger.info("watch_webhook_task_completed")


async def _fire_watch_webhook(webhook: str, url: str, diff_result: dict[str, Any]) -> None:
    """Fire a webhook notification for watch events.

    SSRF guard: ``webhook`` is fully caller-controlled and the request is made
    server-side, so without this gate the free ``/v1/watch`` route is a blind
    internal port-scan primitive (fire-and-forget: the caller only sees timing).
    We reuse the DNS-pinning validator from :mod:`pry.api.webhook_delivery`
    rather than adding a weaker second implementation — it returns a URL whose
    host is replaced by the validated IP, closing the DNS-rebinding TOCTOU
    window between validation and connect. The response body is never logged.
    """
    from pry.api.webhook_delivery import _validate_url

    pinned_url, rejection = _validate_url(webhook)
    if rejection:
        logger.warning(
            "watch_webhook_url_rejected",
            extra={"watch_url": url, "reason": rejection},
        )
        return
    try:
        client = await get_client()
        response = await client.post(
            pinned_url,
            json={"event": "watch_update", "url": url, "data": diff_result},
            timeout=10,
            follow_redirects=False,
            extensions={"sni_hostname": urllib.parse.urlparse(webhook).hostname or ""},
        )
        logger.info(
            "watch_webhook_delivered",
            extra={"watch_url": url, "status_code": response.status_code},
        )
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning(
            "watch_webhook_failed",
            extra={"watch_url": url, "error_type": type(e).__name__},
        )


logger = logging.getLogger(__name__)
