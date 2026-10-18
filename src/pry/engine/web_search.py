"""Pry — Firecrawl-style web search + scrape engine.

Searches the web and returns the full scraped content of each result page
through the Pry anti-bot fallback chain, not just titles and snippets. The
engine chain is SearXNG first, then DuckDuckGo, then the per-engine
modules under :mod:`pry.engine` (seznam, yahoo, qwant, mojeek).

Public API: ``search_web`` only. The scrape/extract variants live in
:mod:`pry.engine.web_search_pipeline` so this module stays engine-thin —
never raises, returning ``{}`` on failure, per the
:mod:`pry.engine.fallback` contract.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import quote_plus, unquote

import httpx

from pry.engine.engine_mojeek import search_mojeek
from pry.engine.engine_qwant import search_qwant
from pry.engine.engine_seznam import search_seznam
from pry.engine.engine_yahoo import search_yahoo
from pry.engine.flaresolverr import fetch_via_flaresolverr
from pry.engine.url_guard import safe_get

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# Instance address is deployment-specific and must not be committed.
_SEARXNG_URL = os.environ.get("PRY_SEARXNG_URL", "http://localhost:8088/search")
_DDG_URL = "https://html.duckduckgo.com/html/"

_DDG_RESULT = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_DDG_SNIPPET = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_DDG_REDIRECT = re.compile(r"[?&]uddg=([^&]+)")


async def _fetch_text(url: str, timeout_s: float = 15.0) -> str:
    """Fetch a URL's text body via the SSRF-safe GET. Returns "" on failure.

    ``follow_redirects=False`` is mandatory: ``safe_get`` validates every
    redirect hop, and an httpx client that follows redirects itself would
    reach a private/metadata target before the guard sees it.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=False,
            headers={"User-Agent": _UA, "Accept": "*/*"},
        ) as client:
            resp = await safe_get(client, url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.debug("web_search_fetch_failed", extra={"url": url, "error": str(exc)})
        return ""


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
        target = f"{_DDG_URL}?q={quote_plus(query)}"
        body = await fetch_via_flaresolverr(target)
        if not body:
            body = await _fetch_text(target)
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
    """Run engines in order; first non-empty answer wins. Never raises."""
    for engine in (
        _search_searxng,
        _search_ddg,
        search_seznam,
        search_yahoo,
        search_qwant,
        search_mojeek,
    ):
        results = await engine(query, num_results)
        if results:
            return results
    return []


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
