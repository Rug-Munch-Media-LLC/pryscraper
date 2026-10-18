"""Pry — scrape + structured-extract pipeline over web search.

Companion to :mod:`pry.engine.web_search`. Split out so the search module a
router imports carries NO engine-internal dependency on
``ultimate_scraper`` (import-linter contract "Routers stay thin").

Public API: ``search_and_scrape``, ``search_and_extract`` — both async, never
raise, returning ``{}`` on failure, per :mod:`pry.engine.fallback`.
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

from pry.engine.web_search import _search

logger = logging.getLogger(__name__)


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


async def _scrape_entry(item: dict[str, Any], scrape: bool) -> dict[str, Any]:
    """Scrape one search hit into a result entry. Never raises."""
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
    return entry


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
        results = [await _scrape_entry(item, scrape) for item in found]
        return {
            "results": results,
            "total": len(results),
            "query": query.strip(),
        }
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.warning("search_and_scrape_failed", extra={"query": query, "error": str(exc)})
        return {}


async def _extract_entry(item: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Scrape one search hit and extract structured data. Never raises."""
    url = item.get("url", "")
    entry: dict[str, Any] = {"url": url, "title": item.get("title", ""), "data": {}}
    if url:
        page = await _scrape_page(url)
        content = page.get("content", "") or ""
        if content:
            _, title = _clean_markdown(content, url)
            if not entry["title"]:
                entry["title"] = title
            entry["data"] = await _extract_data(content, schema)
    return entry


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
        results = [await _extract_entry(item, schema) for item in found]
        return {
            "results": results,
            "total": len(results),
            "query": query.strip(),
        }
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.warning("search_and_extract_failed", extra={"query": query, "error": str(exc)})
        return {}
