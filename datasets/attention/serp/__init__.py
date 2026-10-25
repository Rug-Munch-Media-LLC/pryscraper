"""Pry — Google SERP scraping: organic results + AI Overview + People Also Ask.

Fetches the public Google search results page (no API key, no auth) and
extracts, from the rendered HTML:

* organic results — position, title, URL, snippet
* the AI Overview ("AI Overview" answer box) — text, when present
* People Also Ask (PAA) — related question list, when present

Reliability note: Google's SERP HTML is an ever-moving target (JS A/B
tests, consent walls, login walls). Every extraction here is defensive
and multi-strategy, and the package *never raises* — on any failure
``serp()`` returns ``{"query", "results": [], "ai_overview": None,
"paa": []}`` with an ``error`` key. Consumers must treat the parsed output
as best-effort.

Contract:
    >>> result = await serp("bitcoin price", num=10)
    >>> result["results"][0]["url"]   # https://...
    >>> result["ai_overview"]          # str | None
    >>> result["paa"]                  # [str, ...]

Modules (one concern each): ``config`` (endpoint/headers/retry budget),
``urls`` (href cleaning + query assembly), ``text`` (node text/snippets),
``document`` (lxml parse), ``organic`` / ``ai_overview`` / ``paa``
(result shapes), ``fetch`` (plain HTTP), ``browser`` (egress ladder),
``redirects`` (opaque /goto resolution). This module is the facade — the
public name ``serp`` lives here so callers and tests keep one entry point.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

import httpx

from .ai_overview import _extract_ai_overview
from .browser import _fetch_serp_browser, _proxy_pool, _usable_serp_html
from .config import (
    _HEADERS,
    _MAX_NUM,
    _MIN_USABLE_SERP_BYTES,
    _SERP_URL,
    _TIMEOUT,
    MAX_BACKOFF,
    MAX_RETRIES,
    RETRY_BASE,
)
from .document import _to_root
from .fetch import _fetch_serp, _serp_params, _sleep_backoff
from .organic import _extract_results
from .paa import _extract_paa
from .redirects import _resolve_google_redirects
from .text import _extract_snippet, _text
from .urls import _clean_google_url, _serp_url

logger = logging.getLogger(__name__)

# Compatibility surface: the pre-split module exported these names and callers
# (router, MCP tools, tests) import them from the package.
__all__ = [
    "MAX_BACKOFF",
    "MAX_RETRIES",
    "RETRY_BASE",
    "_HEADERS",
    "_MAX_NUM",
    "_MIN_USABLE_SERP_BYTES",
    "_SERP_URL",
    "_TIMEOUT",
    "_clean_google_url",
    "_extract_ai_overview",
    "_extract_paa",
    "_extract_results",
    "_extract_snippet",
    "_fetch_serp",
    "_fetch_serp_browser",
    "_proxy_pool",
    "_resolve_google_redirects",
    "_serp_params",
    "_serp_url",
    "_sleep_backoff",
    "_text",
    "_to_root",
    "_usable_serp_html",
    "serp",
]


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
        extracted = _extract_results(root, max(num, 1)) if root is not None else []
        if not extracted:
            # plain HTTP was blocked/empty or the DOM shape changed — use the
            # browser ladder and re-parse (a block is a miss, not a success).
            html = await _fetch_serp_browser(query.strip(), num)
            root2 = _to_root(html) if html else None
            if root2 is not None:
                root = root2
                extracted = _extract_results(root, max(num, 1))
        extracted = await _resolve_google_redirects(extracted, max(num, 1))
        return {
            "query": query,
            "results": extracted,
            "ai_overview": _extract_ai_overview(root) if root is not None else None,
            "paa": _extract_paa(root) if root is not None else [],
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
