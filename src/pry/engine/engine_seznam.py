"""Pry — Seznam search engine.

Serves a JS challenge to non-browser clients, so pages are fetched through
FlareSolverr. Results are harvested by anchor and filtered against Seznam's
own chrome, since it exposes no stable result class.
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


_SEZNAM_URL = "https://search.seznam.cz/?q={q}"


async def search_seznam(query: str, num_results: int) -> list[dict[str, Any]]:
    """Seznam via FlareSolverr, extracting outbound links from the result page.

    Seznam does not mark results with a stable class, so anchors are harvested
    and filtered against its own chrome (seznam.cz, mapy.com, static assets).
    """
    try:
        html = await fetch_via_flaresolverr(_SEZNAM_URL.format(q=quote_plus(query)))
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


__all__ = ["search_seznam"]
