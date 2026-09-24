"""Pry — Yahoo search engine.

Serves a JS challenge to non-browser clients, so pages are fetched through
FlareSolverr. Yahoo's own chrome (scout, yimg) is filtered from the results.
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
from urllib.parse import quote_plus

from pry.engine.flaresolverr import fetch_via_flaresolverr

logger = logging.getLogger(__name__)


_TAG = re.compile(r"<[^>]+>")
_YAHOO_URL = "https://search.yahoo.com/search?p={q}"
_EXT_HOSTS = (
    r"yahoo\.com|yimg|scout\.|mojeek\.com|qwant\.com|bing\.com|"
    r"\.css|\.js|\.png|\.svg|\.ico|\.webp"
)


async def search_yahoo(query: str, num_results: int) -> list[dict[str, Any]]:
    """Yahoo via FlareSolverr, filtering its own chrome (scout/yimg)."""
    try:
        html = await fetch_via_flaresolverr(_YAHOO_URL.format(q=quote_plus(query)))
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


__all__ = ["search_yahoo"]
