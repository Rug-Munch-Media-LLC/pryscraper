"""Pry — Firecrawl-style domain mapping + crawl-to-markdown engine.

Maps entire domains (sitemap-first, then internal-link crawling) and converts
crawled pages into clean, chunked Markdown ready for vector databases / RAG
pipelines. All public functions are async, never raise, and return ``{}`` on
failure — mirroring the :mod:`pry.engine.fallback` contract.

Public API:

* ``map_site(url, max_urls, follow_sitemap)`` — discover all URLs on a domain.
* ``crawl_to_markdown(url, max_pages, chunk_size)`` — crawl + clean Markdown chunks.
* ``crawl_for_rag(url, max_pages, chunk_size, chunk_overlap)`` — RAG-ready chunks.

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
from urllib.parse import urlparse

import httpx

from pry.engine.markdown_gen import DefaultMarkdownGenerator, PruningContentFilter

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

_SITEMAP_LOCS = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


# ── Low-level fetch (never raises) ──────────────────────────────────────
async def _fetch_text(url: str, timeout_s: float = 20.0) -> str:
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
        logger.debug("site_mapper_fetch_failed", extra={"url": url, "error": str(exc)})
        return ""


# ── Sitemap discovery ───────────────────────────────────────────────────
async def _sitemap_urls(base_url: str, max_urls: int) -> list[str]:
    """Collect URLs from sitemap.xml (handles sitemap indexes). Never raises."""
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    candidates = [
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap_index.xml",
        f"{origin}/sitemap-index.xml",
    ]
    seen_indexes: set[str] = set()
    urls: list[str] = []
    queue = list(candidates)
    while queue and len(urls) < max_urls:
        sm_url = queue.pop(0)
        if sm_url in seen_indexes:
            continue
        seen_indexes.add(sm_url)
        body = await _fetch_text(sm_url)
        if not body or "<loc" not in body:
            continue
        locs = _SITEMAP_LOCS.findall(body)
        for loc in locs:
            if loc.endswith((".xml", ".xml.gz")) and "sitemap" in loc.lower():
                if len(queue) < 20:
                    queue.append(loc)
            elif len(urls) < max_urls:
                urls.append(loc.split("#")[0].rstrip("/"))
    # Dedupe, preserve order
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:max_urls]


# ── Internal-link crawl discovery ───────────────────────────────────────
async def _crawl_urls(base_url: str, max_urls: int, max_depth: int = 2) -> list[str]:
    """BFS internal-link discovery from a seed URL. Never raises."""
    from pry.engine.scraper import PryScraper

    scraper = PryScraper()
    base_domain = urlparse(base_url).netloc
    visited: set[str] = set()
    to_visit: list[tuple[str, int]] = [(base_url.rstrip("/"), 0)]
    found: list[str] = []
    seen: set[str] = set()
    while to_visit and len(found) < max_urls:
        current, depth = to_visit.pop(0)
        if current in visited or depth > max_depth:
            continue
        visited.add(current)
        try:
            links = await scraper._extract_links(current, {"limit": max_urls - len(found)})
        except Exception as exc:  # noqa: BLE001 - one page failing must not abort
            logger.debug(
                "site_mapper_link_extract_failed", extra={"url": current, "error": str(exc)}
            )
            continue
        for link in links:
            if urlparse(link).netloc != base_domain:
                continue
            if link not in seen:
                seen.add(link)
                found.append(link)
            if depth < max_depth and link not in visited:
                to_visit.append((link, depth + 1))
    return found[:max_urls]


# ── Chunking ────────────────────────────────────────────────────────────
def _chunk_text(text: str, chunk_size: int, overlap: int = 0) -> list[str]:
    """Split text into ~chunk_size-char chunks, preferring paragraph breaks."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # Prefer breaking at a paragraph or sentence boundary.
            window = text[start:end]
            for sep in ("\n\n", "\n", ". "):
                idx = window.rfind(sep)
                if idx > chunk_size // 2:
                    end = start + idx + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, end) if overlap > 0 else end
        if overlap > 0 and start <= (end - overlap):
            start = end - overlap
    return chunks


def _clean_markdown(content: str, url: str) -> tuple[str, str]:
    """Convert raw content to pruned markdown. Returns (markdown, title)."""
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


# ── Page fetching via the anti-bot fallback chain ───────────────────────
async def _scrape_page(url: str) -> dict[str, Any]:
    """Scrape one page through PryScraper (10-tier fallback). Never raises."""
    from pry.engine.scraper import PryScraper

    try:
        scraper = PryScraper()
        return await scraper.scrape(url)
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.debug("site_mapper_scrape_failed", extra={"url": url, "error": str(exc)})
        return {"status": "error", "url": url, "content": ""}


# ── Public API ──────────────────────────────────────────────────────────
async def map_site(url: str, max_urls: int = 100, follow_sitemap: bool = True) -> dict[str, Any]:
    """Map an entire domain: discover all URLs via sitemap + internal-link crawl.

    Checks sitemap.xml first (including sitemap indexes), then crawls internal
    links from the seed URL to fill any remaining budget.

    Returns:
        ``{"urls": [...], "total": N, "sitemap_found": bool, "crawled": bool,
        "base_url": "..."}`` — or ``{}`` on failure. Never raises.
    """
    if not url or not url.startswith(("http://", "https://")):
        return {}
    try:
        base = url.rstrip("/")
        urls: list[str] = []
        sitemap_found = False
        if follow_sitemap:
            urls = await _sitemap_urls(base, max_urls)
            sitemap_found = bool(urls)
        crawled = False
        if len(urls) < max_urls:
            crawled_urls = await _crawl_urls(base, max_urls - len(urls))
            crawled = bool(crawled_urls)
            seen = set(urls)
            for u in crawled_urls:
                if u not in seen and len(urls) < max_urls:
                    seen.add(u)
                    urls.append(u)
        return {
            "urls": urls[:max_urls],
            "total": len(urls[:max_urls]),
            "sitemap_found": sitemap_found,
            "crawled": crawled,
            "base_url": base,
        }
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.warning("map_site_failed", extra={"url": url, "error": str(exc)})
        return {}


async def crawl_to_markdown(
    url: str, max_pages: int = 50, chunk_size: int = 1000
) -> dict[str, Any]:
    """Crawl a site and convert each page to clean, chunked Markdown.

    Maps the domain, then fetches each page through the anti-bot fallback
    chain and converts content to pruned Markdown via
    :mod:`pry.engine.markdown_gen`.

    Returns:
        ``{"pages": [{"url", "markdown", "chunks", "title"}],
        "total_pages": N, "total_chunks": M}`` — or ``{}`` on failure.
    """
    if not url or not url.startswith(("http://", "https://")):
        return {}
    try:
        site = await map_site(url, max_urls=max_pages)
        if not site:
            return {}
        pages: list[dict[str, Any]] = []
        total_chunks = 0
        for page_url in site.get("urls", [])[:max_pages]:
            result = await _scrape_page(page_url)
            content = result.get("content", "") or ""
            if not content:
                continue
            markdown, title = _clean_markdown(content, page_url)
            chunks = _chunk_text(markdown, chunk_size)
            total_chunks += len(chunks)
            pages.append(
                {
                    "url": page_url,
                    "markdown": markdown,
                    "chunks": chunks,
                    "title": title or result.get("title", ""),
                }
            )
        return {
            "pages": pages,
            "total_pages": len(pages),
            "total_chunks": total_chunks,
        }
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.warning("crawl_to_markdown_failed", extra={"url": url, "error": str(exc)})
        return {}


async def crawl_for_rag(
    url: str,
    max_pages: int = 50,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
) -> dict[str, Any]:
    """Crawl a site and produce RAG-ready chunks for vector databases.

    Each chunk carries provenance metadata: ``{"content", "url", "title",
    "chunk_index", "token_estimate"}`` where ``token_estimate`` is
    ``len(content) // 4`` (≈4 chars per token heuristic).

    Returns:
        ``{"chunks": [...], "total_chunks": N, "total_pages": M}`` — or
        ``{}`` on failure. Never raises.
    """
    if not url or not url.startswith(("http://", "https://")):
        return {}
    try:
        crawled = await crawl_to_markdown(url, max_pages=max_pages, chunk_size=chunk_size)
        if not crawled:
            return {}
        rag_chunks: list[dict[str, Any]] = []
        for page in crawled.get("pages", []):
            page_chunks = _chunk_text(page.get("markdown", ""), chunk_size, chunk_overlap)
            for i, chunk in enumerate(page_chunks):
                rag_chunks.append(
                    {
                        "content": chunk,
                        "url": page.get("url", ""),
                        "title": page.get("title", ""),
                        "chunk_index": i,
                        "token_estimate": len(chunk) // 4,
                    }
                )
        return {
            "chunks": rag_chunks,
            "total_chunks": len(rag_chunks),
            "total_pages": crawled.get("total_pages", 0),
        }
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.warning("crawl_for_rag_failed", extra={"url": url, "error": str(exc)})
        return {}


__all__ = ["crawl_for_rag", "crawl_to_markdown", "map_site"]
