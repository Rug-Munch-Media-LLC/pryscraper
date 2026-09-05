"""HTTP transport for retail marketplace scrapers.

Stealth user-agent rotation + optional Webshare residential proxy
(``WEBSHARE_PROXY_LIST`` env var / gopass, see :mod:`webshare_proxy`)
to satisfy geo-gated retailers (Costco needs a US IP) and to dodge
anti-bot challenges from datacenter IPs.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from pry.commerce.marketplace import _http_retries, _rotate_ua
from pry.commerce.marketplace._retail_stores import _BASE_HEADERS, HTTP_TIMEOUT

logger = logging.getLogger(__name__)

RETRY_BASE = 0.5  # seconds — exponential backoff base
MAX_BACKOFF = 3.0  # seconds — backoff cap


def _next_proxy() -> str | None:
    """Next Webshare residential proxy (``WEBSHARE_PROXY_LIST``), or None."""
    try:
        from pry.engine.webshare_proxy import next_webshare_proxy

        return next_webshare_proxy()
    except Exception:
        return None


def _backoff(attempt: int) -> float:
    """Exponential backoff with cap."""
    return float(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))


async def _fetch_page(url: str) -> str | None:
    """GET a retail page (stealth UA + optional Webshare proxy); None on failure.

    Never raises. Retries with capped backoff on 429 / 5xx / transport
    errors; treats any 4xx as a hard failure.
    """
    proxy = _next_proxy()
    attempts = _http_retries()
    for attempt in range(attempts):
        try:
            headers = {"User-Agent": _rotate_ua()}
            headers.update(_BASE_HEADERS)
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT,
                proxy=proxy,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = await client.get(url)
            if resp.status_code in (429,) or resp.status_code >= 500:
                if attempt + 1 < attempts:
                    await asyncio.sleep(_backoff(attempt))
                continue
            if resp.status_code >= 400:
                return None
            return resp.text
        except httpx.HTTPError as exc:
            logger.warning(
                "retail_http_error",
                extra={"url": url[:140], "error": str(exc)[:140], "attempt": attempt},
            )
            if attempt + 1 < attempts:
                await asyncio.sleep(_backoff(attempt))
            continue
    return None
