"""Pry — Google SERP scraping: organic results + AI Overview + People Also Ask.

Fetches the public Google search results page (no API key, no auth) and
extracts, from the rendered HTML:

* organic results — position, title, URL, snippet
* the AI Overview ("AI Overview" answer box) — text, when present
* People Also Ask (PAA) — related question list, when present

Reliability note: Google's SERP HTML is an ever-moving target (JS A/B
tests, consent walls, login walls). Every extraction here is defensive
and multi-strategy, and the module *never raises* — on any failure it
returns ``{"query", "results": [], "ai_overview": None, "paa": []}`` with
an ``error`` key. Consumers must treat the parsed output as best-effort.

Contract:
    >>> result = await serp("bitcoin price", num=10)
    >>> result["results"][0]["url"]   # https://...
    >>> result["ai_overview"]          # str | None
    >>> result["paa"]                  # [str, ...]

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

_SERP_URL = "https://www.google.com/search"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 2

_MAX_NUM = 100


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (never raises)."""
    await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))


def _text(el: Any) -> str:
    """Collapse an lxml element's text content into a single line."""
    try:
        return " ".join((el.text_content() or "").split())
    except (AttributeError, TypeError, ValueError):
        return ""


def _clean_google_url(href: str) -> str:
    """Resolve a Google result href to the real destination URL.

    Modern SERPs wrap organic links as ``/url?q=<target>&sa=U&...``;
    older layouts link directly. Returns ``""`` when the href is not a
    usable organic result link.
    """
    if not href:
        return ""
    if href.startswith("/url?"):
        q = parse_qs(urlparse(href).query).get("q")
        if not q:
            return ""
        target = q[0]
        if "google." in urlparse(target).netloc:
            return ""
        return target
    if href.startswith(("http://", "https://")):
        netloc = urlparse(href).netloc
        if "google." not in netloc:
            return href
    return ""


def _extract_snippet(block: Any) -> str:
    """Best-effort snippet extraction from one organic result block."""
    for selector in (".VwiC3b", "div[data-sncf]", ".IsZvec", ".aCOpRe"):
        try:
            els = block.cssselect(selector)
        except (AttributeError, TypeError, ValueError):
            continue
        if els:
            text = _text(els[0])
            if text:
                return text
    return ""


def _extract_results(root: Any, num: int) -> list[dict[str, Any]]:
    """Extract organic results from the parsed SERP document.

    Strategy A targets the current ``div.MjjYud`` / ``div.g`` wrappers;
    for each wrapper it finds the first ``<a>`` wrapping an ``<h3>``
    (the organic title link), resolves the href, and grabs the snippet
    from the known snippet classes.
    """
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        blocks = root.cssselect(".MjjYud") or root.cssselect("div.g")
    except (AttributeError, TypeError, ValueError):
        return results
    for block in blocks:
        anchor: Any | None = None
        try:
            for a in block.cssselect("a[href]"):
                if a.cssselect("h3"):
                    anchor = a
                    break
        except (AttributeError, TypeError, ValueError):
            continue
        if anchor is None:
            continue
        url = _clean_google_url(anchor.get("href", ""))
        if not url or url in seen:
            continue
        try:
            title = _text(anchor.cssselect("h3")[0])
        except (AttributeError, TypeError, ValueError, IndexError):
            title = ""
        if not title:
            continue
        seen.add(url)
        results.append(
            {
                "position": len(results) + 1,
                "title": title,
                "url": url,
                "snippet": _extract_snippet(block),
            }
        )
        if len(results) >= max(num, 1):
            break
    return results


def _extract_ai_overview(root: Any) -> str | None:
    """Best-effort AI Overview extraction (heuristic, changes often)."""
    # Strategy A: known AI-overview container classes / attrs.
    for selector in (
        "div.ILfuVd",
        "div[data-attrid='kAAb9c']",
        "div[data-attrid='knowledge-answer']",
    ):
        try:
            els = root.cssselect(selector)
        except (AttributeError, TypeError, ValueError):
            continue
        for el in els:
            text = _text(el)
            if text:
                if text.startswith("AI Overview"):
                    text = text[len("AI Overview") :].strip()
                return text or None
    # Strategy B: find the literal "AI Overview" label and return the
    # enclosing block's text (label stripped).
    try:
        for el in root.iter():
            tag = el.tag
            if not isinstance(tag, str) or tag not in ("div", "span", "h2", "section", "article"):
                continue
            direct = (el.text or "").strip()
            if not direct.startswith("AI Overview"):
                continue
            parent = el.getparent()
            if parent is None:
                return " ".join(direct.split())
            text = " ".join((parent.text_content() or "").split())
            if text.startswith("AI Overview"):
                text = text[len("AI Overview") :].strip()
            if len(text) > 10:
                return text[:2000]
            return " ".join(direct.split())
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _extract_paa(root: Any) -> list[str]:
    """Best-effort People-Also-Ask extraction (heuristic, changes often)."""
    questions: list[str] = []
    # Strategy A: legacy "related-question-pair" blocks.
    try:
        pairs = root.cssselect("div.related-question-pair")
    except (AttributeError, TypeError, ValueError):
        pairs = []
    for el in pairs:
        q = _text(el)
        if q and q not in questions:
            questions.append(q)
    if questions:
        return questions[:10]
    # Strategy B: locate the "People also ask" label, then walk up to the
    # smallest container that holds heading-like questions.
    try:
        for el in root.iter():
            tag = el.tag
            if not isinstance(tag, str) or tag not in ("h3", "span", "div", "section"):
                continue
            if (el.text or "").strip() != "People also ask":
                continue
            container = el.getparent()
            for _ in range(4):
                if container is None:
                    break
                headings = []
                for h in container.cssselect("h3"):
                    q = _text(h)
                    if q and q != "People also ask" and q not in questions:
                        headings.append(q)
                if headings:
                    questions.extend(headings)
                    return questions[:10]
                container = container.getparent()
            return questions[:10]
    except (AttributeError, TypeError, ValueError):
        return questions
    return questions


async def _fetch_serp(query: str, num: int) -> str:
    """Fetch the SERP HTML with capped exponential backoff (never raises)."""
    from pry.api.client import get_client

    client = await get_client()
    params = {
        "q": query,
        "num": str(min(max(num, 1), _MAX_NUM)),
        "hl": "en",
        "gl": "us",
        "pws": "0",
    }
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.get(
                _SERP_URL,
                params=params,
                headers=_HEADERS,
                timeout=_TIMEOUT,
                follow_redirects=True,
            )
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                return ""
            return resp.text
        except httpx.HTTPError as exc:  # transport / timeout / redirect errors
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("serp_fetch_failed", extra={"query": query[:80], "error": last_error})
    return ""


def _to_root(html: str) -> Any | None:
    """Parse HTML into an lxml root, or None (never raises)."""
    try:
        from lxml import html as lxml_html

        return lxml_html.fromstring(html)
    except (AttributeError, TypeError, ValueError, ImportError):
        return None


async def serp(query: str, num: int = 10) -> dict[str, Any]:
    """Scrape Google SERP for ``query``: organic results, AI Overview, PAA.

    Never raises. On failure returns the full shape with empty lists and
    an ``error`` key.
    """
    if not query or not query.strip():
        return {
            "query": query,
            "results": [],
            "ai_overview": None,
            "paa": [],
            "error": "empty query",
        }
    try:
        html = await _fetch_serp(query.strip(), num)
        if not html:
            return {
                "query": query,
                "results": [],
                "ai_overview": None,
                "paa": [],
                "error": "empty response",
            }
        root = _to_root(html)
        if root is None:
            return {
                "query": query,
                "results": [],
                "ai_overview": None,
                "paa": [],
                "error": "parse failed",
            }
        return {
            "query": query,
            "results": _extract_results(root, max(num, 1)),
            "ai_overview": _extract_ai_overview(root),
            "paa": _extract_paa(root),
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        logger.warning("serp_failed", extra={"query": query[:80], "error": str(exc)[:200]})
        return {
            "query": query,
            "results": [],
            "ai_overview": None,
            "paa": [],
            "error": str(exc)[:200],
        }
