"""Pry — browser-tier SERP fetch across the residential egress ladder."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import os
import re

import httpx

from .config import _MIN_USABLE_SERP_BYTES
from .urls import _serp_url

logger = logging.getLogger(__name__)


def _usable_serp_html(html: str) -> bool:
    """True when a fetched page is plausibly a results SERP, not a block shell.

    Google answers a blocked datacenter IP with a tiny consent/interstitial page
    (~6 KB, no headings). A usable page has organic <h3> headings and real size.
    A block is a MISS, not a success.
    """
    return bool(html) and len(html) >= _MIN_USABLE_SERP_BYTES and "<h3" in html


def _proxy_pool() -> list[str]:
    """Residential egress pool from WEBSHARE_PROXY_LIST (space/comma separated)."""
    raw = (os.environ.get("WEBSHARE_PROXY_LIST") or "").strip()
    return [p for p in re.split(r"[\s,]+", raw) if p.startswith("http")]


async def _fetch_serp_browser(query: str, num: int) -> str:
    """Fetch the SERP through the browser tier, retrying across egress.

    Google blocks a bare datacenter IP; first-party Pry ships the FlareSolverr
    ladder used by the other engines. We try the direct browser first, then
    rotate the residential proxy pool, accepting the first page that passes the
    usable-shape check. Never raises; "" when no tier yields a usable page.
    """
    try:
        from pry.engine.flaresolverr import fetch_via_flaresolverr
    except ImportError as exc:
        logger.warning("serp_browser_unavailable", extra={"error": str(exc)[:160]})
        return ""

    url = _serp_url(query, num)
    last_html = ""
    # tier 1: direct browser; tier 2..: one attempt per residential proxy.
    for proxy in [None, *_proxy_pool()[:4]]:
        try:
            html = await fetch_via_flaresolverr(url, proxy=proxy) or ""
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            logger.warning(
                "serp_browser_fetch_failed",
                extra={"proxied": proxy is not None, "error": str(exc)[:160]},
            )
            continue
        last_html = html
        if _usable_serp_html(html):
            return html
    return last_html if _usable_serp_html(last_html) else ""
