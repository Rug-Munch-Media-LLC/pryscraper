"""Pry — Firecrawl-style web search + scrape engine.

Searches the web (SearXNG primary, DuckDuckGo HTML fallback) and returns the
full scraped content of each result page through the Pry anti-bot fallback
chain — not just titles and snippets. All public functions are async, never
raise, and return ``{}`` on failure — mirroring the
:mod:`pry.engine.fallback` contract.

Public API:

* ``search_web(query, num_results)`` — search only, titles + snippets.
* ``search_and_scrape(query, num_results, scrape)`` — search + full page content.
* ``search_and_extract(query, schema, num_results)`` — search + scrape + structured extraction.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus, unquote

import httpx

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

_SEARXNG_URL = "http://localhost:8089/search"
_DDG_URL = "https://html.duckduckgo.com/html/"

# DuckDuckGo HTML result parsing
_DDG_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.I | re.S,
)
_DDG_SNIPPET = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
# DDG wraps URLs in a redirect: //duckduckgo.com/l/?uddg=<encoded>&rut=...
_DDG_REDIRECT = re.compile(r"[?&]uddg=([^&]+)")


# ── Low-level fetch (never raises) ──────────────────────────────────────
async def _fetch_text(url: str, timeout_s: float = 15.0) -> str:
    """Fetch a URL's text body via httpx. Returns "" on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=True,
            headers={"User-Agent": _UA, "Accept": "*/*"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.debug("web_search_fetch_failed", extra={"url": url, "error": str(exc)})
        return ""


# ── Search engines (never raise) ────────────────────────────────────────
async def _search_searxng(query: str, num_results: int) -> list[dict[str, Any]]:
    """Search via self-hosted SearXNG JSON API. Returns [] on failure."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            headers={"User-Agent": _UA, "Accept": "application/json"},
        ) as client:
            resp = await client.get(
                _SEARXNG_URL,
                params={"q": query, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
        results: list[dict[str, Any]] = []
        for item in data.get("results", [])[:num_results]:
            url = item.get("url", "")
            if not url:
                continue
            results.append(
                {
                    "url": url,
                    "title": item.get("title", ""),
                    "snippet": item.get("content", "") or "",
                }
            )
        return results
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.debug("searxng_search_failed", extra={"error": str(exc)})
        return []


def _unwrap_ddg_url(href: str) -> str:
    """Resolve DuckDuckGo redirect links to the real target URL."""
    if "uddg=" in href:
        match = _DDG_REDIRECT.search(href)
        if match:
            return unquote(match.group(1))
    return href


async def _search_ddg(query: str, num_results: int) -> list[dict[str, Any]]:
    """Search via DuckDuckGo HTML endpoint. Returns [] on failure."""
    try:
        body = await _fetch_text(f"{_DDG_URL}?q={quote_plus(query)}")
        if not body:
            return []
        results: list[dict[str, Any]] = []
        snippets = _DDG_SNIPPET.findall(body)
        for i, (href, title) in enumerate(_DDG_RESULT.findall(body)):
            if len(results) >= num_results:
                break
            url = _unwrap_ddg_url(href)
            if not url.startswith(("http://", "https://")):
                continue
            snippet = _TAG.sub("", snippets[i]) if i < len(snippets) else ""
            results.append(
                {
                    "url": url,
                    "title": _TAG.sub("", title).strip(),
                    "snippet": snippet.strip(),
                }
            )
        return results
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.debug("ddg_search_failed", extra={"error": str(exc)})
        return []


async def _search(query: str, num_results: int) -> list[dict[str, Any]]:
    """Search with SearXNG primary, DuckDuckGo HTML fallback. Never raises."""
    results = await _search_searxng(query, num_results)
    if results:
        return results
    return await _search_ddg(query, num_results)


# ── Scraping via the anti-bot fallback chain (never raises) ─────────────
async def _scrape_page(url: str) -> dict[str, Any]:
    """Scrape one page through the 15-tier anti-bot chain. Never raises."""
    from pry.engine.ultimate_scraper import UltimateScraper

    try:
        scraper = UltimateScraper()
        return await scraper.scrape(url)
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.debug("web_search_scrape_failed", extra={"url": url, "error": str(exc)})
        return {"status": "error", "url": url, "content": ""}


def _clean_markdown(content: str, url: str) -> tuple[str, str]:
    """Convert raw content to pruned markdown. Returns (markdown, title)."""
    from pry.engine.markdown_gen import DefaultMarkdownGenerator, PruningContentFilter

    gen = DefaultMarkdownGenerator(content_filter=PruningContentFilter(threshold=0.3))
    try:
        result = gen.generate(content, url=url)
    except Exception:  # noqa: BLE001 - contract: never raise
        result = {"raw_markdown": content}
    markdown = result.get("fit_markdown") or result.get("raw_markdown") or ""
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    title = ""
    for line in markdown.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return markdown, title


# ── Structured extraction (never raises) ────────────────────────────────
async def _extract_data(content: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Extract structured fields from page content using SchemaExtractor."""
    from pry.engine.extractor import SchemaExtractor

    try:
        extractor = SchemaExtractor()
        return await extractor.extract(content, schema)
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.debug("web_search_extract_failed", extra={"error": str(exc)})
        return {}


# ── Public API ──────────────────────────────────────────────────────────
async def search_web(query: str, num_results: int = 10) -> dict[str, Any]:
    """Search the web and return titles + snippets only (no scraping).

    Uses self-hosted SearXNG (free, no key) with DuckDuckGo HTML fallback.

    Returns:
        ``{"results": [{"url", "title", "snippet"}], "total": N,
        "query": "..."}`` — or ``{}`` on failure. Never raises.
    """
    if not query or not query.strip():
        return {}
    try:
        results = await _search(query.strip(), num_results)
        return {"results": results, "total": len(results), "query": query.strip()}
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.warning("search_web_failed", extra={"query": query, "error": str(exc)})
        return {}


async def search_and_scrape(
    query: str, num_results: int = 5, scrape: bool = True
) -> dict[str, Any]:
    """Search the web and return the full scraped content of each result page.

    Firecrawl-style: unlike a plain SERP scraper, each result carries the
    full page ``content`` and clean ``markdown`` fetched through the Pry
    15-tier anti-bot fallback chain.

    Returns:
        ``{"results": [{"url", "title", "snippet", "content", "markdown"}],
        "total": N, "query": "..."}`` — or ``{}`` on failure. Never raises.
    """
    if not query or not query.strip():
        return {}
    try:
        found = await _search(query.strip(), num_results)
        if not found:
            return {"results": [], "total": 0, "query": query.strip()}
        results: list[dict[str, Any]] = []
        for item in found:
            entry: dict[str, Any] = {
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "content": "",
                "markdown": "",
            }
            if scrape and entry["url"]:
                page = await _scrape_page(entry["url"])
                content = page.get("content", "") or ""
                if content:
                    markdown, title = _clean_markdown(content, entry["url"])
                    entry["content"] = content
                    entry["markdown"] = markdown
                    if not entry["title"]:
                        entry["title"] = title
            results.append(entry)
        return {
            "results": results,
            "total": len(results),
            "query": query.strip(),
        }
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.warning("search_and_scrape_failed", extra={"query": query, "error": str(exc)})
        return {}


async def search_and_extract(
    query: str, schema: dict[str, Any], num_results: int = 5
) -> dict[str, Any]:
    """Search, scrape each result, and extract structured data per page.

    Schema format: ``{"field_name": "description of what to extract"}``
    (pattern extraction first, LLM fallback for complex schemas).

    Returns:
        ``{"results": [{"url", "title", "data": {...}}], "total": N,
        "query": "..."}`` — or ``{}`` on failure. Never raises.
    """
    if not query or not query.strip() or not isinstance(schema, dict) or not schema:
        return {}
    try:
        found = await _search(query.strip(), num_results)
        if not found:
            return {"results": [], "total": 0, "query": query.strip()}
        results: list[dict[str, Any]] = []
        for item in found:
            url = item.get("url", "")
            entry: dict[str, Any] = {
                "url": url,
                "title": item.get("title", ""),
                "data": {},
            }
            if url:
                page = await _scrape_page(url)
                content = page.get("content", "") or ""
                if content:
                    _, title = _clean_markdown(content, url)
                    if not entry["title"]:
                        entry["title"] = title
                    entry["data"] = await _extract_data(content, schema)
            results.append(entry)
        return {
            "results": results,
            "total": len(results),
            "query": query.strip(),
        }
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.warning("search_and_extract_failed", extra={"query": query, "error": str(exc)})
        return {}


__all__ = ["search_and_extract", "search_and_scrape", "search_web"]
