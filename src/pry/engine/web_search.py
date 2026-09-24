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
import os
import re
from typing import Any
from urllib.parse import quote_plus, unquote

import httpx

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# Instance address is deployment-specific and must not be committed.
_SEARXNG_URL = os.environ.get("PRY_SEARXNG_URL", "http://localhost:8088/search")
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


# ── FlareSolverr fetch (defeats JS/bot challenges) ───────────────────────────
_FLARESOLVERR_URL = os.environ.get("PRY_FLARESOLVERR_URL", "http://flaresolverr-pry:8191/v1")


async def _fetch_via_flaresolverr(url: str, timeout_s: float = 90.0) -> str:
    """Fetch a URL through FlareSolverr. Returns "" when unavailable.

    DuckDuckGo answers plain HTTP clients with a 202 challenge page that
    contains no results, and it ignores both IP reputation (the same 202
    comes back through every residential proxy) and a spoofed user agent.
    FlareSolverr runs a real browser and clears the challenge, so the DDG
    HTML endpoint returns parseable results.
    """
    try:
        payload = {"cmd": "request.get", "url": url, "maxTimeout": int(timeout_s * 1000)}
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.post(_FLARESOLVERR_URL, json=payload)
            resp.raise_for_status()
            return (resp.json().get("solution") or {}).get("response", "") or ""
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.debug("flaresolverr_fetch_failed", extra={"url": url, "error": str(exc)})
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
        target = f"{_DDG_URL}?q={quote_plus(query)}"
        body = await _fetch_via_flaresolverr(target)
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
    """Search with SearXNG primary, DuckDuckGo HTML fallback. Never raises."""
    for engine in (
        _search_searxng,
        _search_ddg,
        _search_seznam,
        _search_yahoo,
        _search_qwant,
        _search_mojeek,
    ):
        results = await engine(query, num_results)
        if results:
            return results
    return []


# ── Additional engines (FlareSolverr / JSON API) ────────────────────────────
_SEZNAM_URL = "https://search.seznam.cz/?q={q}"
_YAHOO_URL = "https://search.yahoo.com/search?p={q}"
_QWANT_API = "https://api.qwant.com/v3/search/web?q={q}&count=10&locale=en_US&safesearch=1&tgp=3"
_EXT_HOSTS = (
    r"yahoo\.com|yimg|scout\.|mojeek\.com|qwant\.com|bing\.com|"
    r"\.css|\.js|\.png|\.svg|\.ico|\.webp"
)


_MOJEEK_URL = "https://www.mojeek.com/search?q={q}"


async def _search_mojeek(query: str, num_results: int) -> list[dict[str, Any]]:
    """Mojeek via headless Chromium, solving its Altcha proof-of-work.

    Mojeek gates every query with an Altcha PBKDF2 widget that only starts on
    a *trusted* pointer event, so ``element.click()`` is ignored and the widget
    stays "unverified" forever. A real mouse down/up on the checkbox lets the
    widget run its own PoW, after which the session is cleared for normal
    searching. FlareSolverr cannot do this: it never emits pointer events.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001 - optional dependency
        logger.debug("mojeek_playwright_missing", extra={"error": str(exc)})
        return []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            try:
                ctx = await browser.new_context(
                    user_agent=_UA, locale="en-US", viewport={"width": 1400, "height": 900}
                )
                page = await ctx.new_page()
                await page.goto(
                    _MOJEEK_URL.format(q=quote_plus(query)),
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await page.wait_for_timeout(2500)
                box = await page.query_selector(".altcha-checkbox-wrap")
                if box:
                    bb = await box.bounding_box()
                    if bb:
                        await page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                        await page.mouse.down()
                        await page.wait_for_timeout(150)
                        await page.mouse.up()
                        for _ in range(20):
                            await page.wait_for_timeout(1500)
                            try:
                                state = await page.evaluate(
                                    "()=>document.querySelector('.altcha')?.getAttribute('data-state')"
                                )
                            except Exception:  # noqa: BLE001 - Altcha navigates on verify
                                # The widget POSTs to /captcha/verify, which destroys
                                # the execution context; that navigation IS the success.
                                state = "verified"
                            if state == "verified" or state is None:
                                break
                    await page.goto(
                        _MOJEEK_URL.format(q=quote_plus(query)),
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    await page.wait_for_timeout(1500)
                    # Mojeek re-challenges under rapid querying; retry once after a settle.
                    if "captcha" in (await page.title()).lower():
                        await page.wait_for_timeout(9000)
                        await page.goto(
                            _MOJEEK_URL.format(q=quote_plus(query)),
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )
                        await page.wait_for_timeout(3000)
                html = await page.content()
            finally:
                await browser.close()
        links = re.findall(r'<a[^>]+class="ob"[^>]+href="(https?://[^"]+)"', html, re.I)
        if not links:
            links = re.findall(r'<h2><a[^>]+href="(https?://[^"]+)"', html, re.I)
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for href in links:
            if href in seen or re.search(r"mojeek\.com|\.css|\.js|\.png|\.svg|\.ico", href):
                continue
            seen.add(href)
            out.append({"url": href, "title": "", "snippet": ""})
            if len(out) >= num_results:
                break
        return out
    except Exception as exc:  # noqa: BLE001 - never raise
        logger.debug("mojeek_search_failed", extra={"error": str(exc)})
        return []


async def _search_seznam(query: str, num_results: int) -> list[dict[str, Any]]:
    """Seznam via FlareSolverr, extracting outbound links from the result page.

    Seznam does not mark results with a stable class, so anchors are harvested
    and filtered against its own chrome (seznam.cz, mapy.com, static assets).
    """
    try:
        html = await _fetch_via_flaresolverr(_SEZNAM_URL.format(q=quote_plus(query)))
        if not html:
            return []
        skip = re.compile(
            r"seznam\.cz|mapy\.com|firma\.cz|firmy\.cz|\.css|\.js|\.png|\.svg|\.ico|\.webp|\.woff",
            re.I,
        )
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for href in re.findall(r'href="(https?://[^"]+)"', html):
            if skip.search(href) or href in seen:
                continue
            seen.add(href)
            out.append({"url": href, "title": "", "snippet": ""})
            if len(out) >= num_results:
                break
        return out
    except Exception as exc:  # noqa: BLE001 - never raise
        logger.debug("seznam_search_failed", extra={"error": str(exc)})
        return []


async def _search_yahoo(query: str, num_results: int) -> list[dict[str, Any]]:
    """Yahoo via FlareSolverr, filtering its own chrome (scout/yimg)."""
    try:
        html = await _fetch_via_flaresolverr(_YAHOO_URL.format(q=quote_plus(query)))
        if not html:
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for href, title in re.findall(
            r'<h3[^>]*>.*?<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            html,
            re.I | re.S,
        ):
            if re.search(_EXT_HOSTS, href) or href in seen:
                continue
            seen.add(href)
            out.append({"url": href, "title": _TAG.sub("", title).strip()[:200], "snippet": ""})
            if len(out) >= num_results:
                break
        return out
    except Exception as exc:  # noqa: BLE001 - never raise
        logger.debug("yahoo_search_failed", extra={"error": str(exc)})
        return []


async def _search_qwant(query: str, num_results: int) -> list[dict[str, Any]]:
    """Qwant via its JSON API (the HTML app is JS-hydrated and yields no anchors)."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={
                "User-Agent": _UA,
                "Accept": "application/json",
                "Referer": "https://www.qwant.com/",
            },
        ) as client:
            resp = await client.get(_QWANT_API.format(q=quote_plus(query)))
            resp.raise_for_status()
            payload = resp.json()
        out: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if len(out) >= num_results:
                return
            if isinstance(node, dict):
                if node.get("url") and node.get("title"):
                    out.append(
                        {
                            "url": node["url"],
                            "title": str(node["title"])[:200],
                            "snippet": str(node.get("desc") or node.get("description") or ""),
                        }
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        return out[:num_results]
    except Exception as exc:  # noqa: BLE001 - never raise
        logger.debug("qwant_search_failed", extra={"error": str(exc)})
        return []


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
