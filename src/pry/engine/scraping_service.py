"""Pry — scraping service: format extras and detection helpers.

Engine-side home for the work the scraping routes used to do inline:
Firecrawl format normalisation, HTML→markdown/links/images extras, and
anti-bot / lazy-content detection. Part of Pry (MIT).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import httpx
from lxml import html as lxml_html

from pry.core.errors import ScrapeError
from pry.core.settings import settings
from pry.engine.lazy_load import (
    detect_lazy_loading,
    generate_load_more_script,
    generate_scroll_script,
)
from pry.engine.scraper import BlockDetector
from pry.engine.url_guard import safe_get, validate_url

logger = logging.getLogger(__name__)

FORMATS = frozenset({"markdown", "html", "rawHtml", "links", "images", "screenshot", "pdf"})
_FORMAT_ALIASES = {"rawhtml": "rawHtml", "raw_html": "rawHtml", "raw-html": "rawHtml"}
_LINK_CAP = 1000
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def requested_formats(formats: list[str] | None) -> set[str]:
    """Normalise ``formats``; unknown values are dropped, markdown always on."""
    requested = {"markdown"}
    for raw in formats or []:
        name = _FORMAT_ALIASES.get(str(raw).strip().lower(), str(raw).strip())
        if name in FORMATS:
            requested.add(name)
    return requested


def _absolutise(values: list[str], base: str, *, allow_data: bool = False) -> list[str]:
    """Resolve, de-duplicate and cap a list of URL attributes."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        candidate = urljoin(base, value.strip())
        if allow_data and candidate.startswith("data:"):
            pass
        elif not candidate.startswith(("http://", "https://")):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        out.append(candidate)
        if len(out) >= _LINK_CAP:
            break
    return out


def _cleaned_html(raw_html: str) -> str:
    """Readability-cleaned article HTML, falling back to the page source."""
    if not raw_html:
        return ""
    try:
        from readability import Document

        summary = Document(raw_html).summary()
        if summary:
            return summary
    except Exception:
        logger.debug("readability_failed", exc_info=True)
    return raw_html


def format_extras(requested: set[str], raw_html: str, base: str) -> dict[str, Any]:
    """Optional response keys; one parse, degrading to source on failure."""
    extras: dict[str, Any] = {}
    if "rawHtml" in requested:
        extras["rawHtml"] = raw_html
    tree = None
    if raw_html and requested & {"html", "links", "images"}:
        try:
            tree = lxml_html.fromstring(raw_html)
        except (ValueError, TypeError):
            tree = None
    if "html" in requested:
        extras["html"] = _cleaned_html(raw_html)
    if "links" in requested:
        hrefs = tree.xpath("//a/@href") if tree is not None else []
        extras["links"] = _absolutise(hrefs, base)
    if "images" in requested:
        srcs = tree.xpath("//img/@src") if tree is not None else []
        extras["images"] = _absolutise(srcs, base, allow_data=True)
    return extras


_media_engine: Any = None


async def render_media_for(scraper: Any, url: str, **kwargs: Any) -> dict[str, Any]:
    """Render screenshot/PDF through the engine hook on ``scraper``.

    ``PryScraper`` is a wrapper without the hook, so fall back to one lazy
    ``UltimateScraper`` — the hook reuses the process-wide BrowserPool, so this
    is still a single browser path and never a second implementation.
    """
    hook = getattr(scraper, "render_media", None)
    if hook is None:
        global _media_engine
        if _media_engine is None:
            from pry.engine.ultimate_scraper import UltimateScraper

            _media_engine = UltimateScraper()
        hook = _media_engine.render_media
    return await hook(url, **kwargs)


async def detect_block(url: str, get_client: Any) -> dict[str, Any]:
    """Detect anti-bot protection (tier, vendor, confidence)."""
    validate_url(url)
    client = await get_client()
    detector = BlockDetector()
    results: list[dict[str, Any]] = []
    try:
        resp = await safe_get(client, url, timeout=15, headers={"User-Agent": _BROWSER_UA})
        results.append(
            {
                "method": "direct",
                "status": resp.status_code,
                **detector.detect(resp.text, resp.status_code, dict(resp.headers)),
            }
        )
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning("scraping_exception_handler", exc_info=True)
        results.append({"method": "direct", "error": str(e)})
    try:
        async with httpx.AsyncClient(timeout=30) as fs_client:
            fs_resp = await fs_client.post(
                settings.flaresolverr_url,
                json={"cmd": "request.get", "url": url, "maxTimeout": 15000},
            )
            if fs_resp.is_success:
                fs_data = fs_resp.json()
                fs_html = fs_data.get("solution", {}).get("response", "")
                fs_status = fs_data.get("solution", {}).get("status", 0)
                results.append(
                    {
                        "method": "flaresolverr",
                        "status": fs_status,
                        **detector.detect(fs_html, fs_status),
                    }
                )
            else:
                results.append({"method": "flaresolverr", "error": f"HTTP {fs_resp.status_code}"})
    except (httpx.HTTPError, httpx.RequestError) as e:
        logger.warning("scraping_exception_handler", exc_info=True)
        results.append({"method": "flaresolverr", "error": str(e)})
    return {"success": True, "data": {"url": url, "results": results}}


async def detect_lazy_content(
    url: str, *, scraper: Any, get_client: Any, auto_scroll: bool, max_scrolls: int
) -> dict[str, Any]:
    """Fetch a page, detect lazy loading, and optionally emit scroll scripts."""
    validate_url(url)
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")
    html = result.get("raw_html", "")
    if not html:
        client = await get_client()
        try:
            resp = await safe_get(client, url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            html = resp.text
        except (httpx.HTTPError, httpx.RequestError):
            raise ScrapeError("Could not fetch raw HTML") from None
    detection = detect_lazy_loading(html)
    return {
        "url": url,
        "detection": detection,
        "has_lazy_content": any(detection.values()),
        "scroll_script": generate_scroll_script(max_scrolls=max_scrolls) if auto_scroll else "",
        "load_more_script": generate_load_more_script() if auto_scroll else "",
    }
