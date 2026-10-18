"""Pry — fetch a URL through FlareSolverr, which runs a real browser.

Several search engines answer plain HTTP clients with a challenge page that
contains no results, and they ignore both a spoofed user agent and
residential proxy rotation: the block is behavioural, not IP reputation.
FlareSolverr clears it.

This module is transport only. Engines live in :mod:`pry.engine.engines_api`
and :mod:`pry.engine.engines_browser`.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import validate_url

logger = logging.getLogger(__name__)

_FLARESOLVERR_URL = os.environ.get("PRY_FLARESOLVERR_URL", "http://flaresolverr-pry:8191/v1")


_FLARESOLVERR_URL = os.environ.get("PRY_FLARESOLVERR_URL", "http://flaresolverr-pry:8191/v1")


async def fetch_via_flaresolverr(
    url: str, timeout_s: float = 90.0, proxy: str | None = None
) -> str:
    """Fetch a URL through FlareSolverr. Returns "" when unavailable.

    DuckDuckGo answers plain HTTP clients with a 202 challenge page that
    contains no results, and it ignores both IP reputation (the same 202
    comes back through every residential proxy) and a spoofed user agent.
    FlareSolverr runs a real browser and clears the challenge, so the DDG
    HTML endpoint returns parseable results.
    """
    # The caller URL is posted to FlareSolverr, which navigates a real browser
    # and follows redirects itself. Validate BEFORE posting: otherwise the
    # browser is the SSRF client and the redirect hops are invisible to us.
    try:
        validate_url(url)
    except InvalidRequestError as exc:
        logger.warning("flaresolverr_url_rejected", extra={"url": url, "reason": str(exc)})
        return ""

    try:
        payload: dict[str, Any] = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": int(timeout_s * 1000),
        }
        # Residential egress: Google/DuckDuckGo block a bare datacenter IP. When a
        # proxy is supplied it is handed to FlareSolverr's own ``proxy`` field so
        # the browser exits through it. (Rotation pool: gopass
        # rmi/infra/webshare_proxy_list_v2; see docs/ops/site-access-playbook.md.)
        if proxy:
            payload["proxy"] = {"url": proxy}
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.post(_FLARESOLVERR_URL, json=payload)
            resp.raise_for_status()
            solution = resp.json().get("solution") or {}
            final_url = solution.get("url") or ""
            if final_url:
                # A redirect inside the browser can land on a private target;
                # validate where it actually ended up before trusting the body.
                try:
                    validate_url(final_url)
                except InvalidRequestError as exc:
                    logger.warning(
                        "flaresolverr_final_url_rejected",
                        extra={"url": final_url, "reason": str(exc)},
                    )
                    return ""
            return solution.get("response", "") or ""
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        logger.debug("flaresolverr_fetch_failed", extra={"url": url, "error": str(exc)})
        return ""


__all__ = ["fetch_via_flaresolverr"]
