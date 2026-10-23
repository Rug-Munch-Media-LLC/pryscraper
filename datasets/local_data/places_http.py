"""HTTP fetching and robots.txt compliance for local_data.places.

Split from ``places.py``: the retrying ``_http_get`` wrapper (browser
headers, timeouts, exponential backoff honoring Retry-After) and the
best-effort, fail-open ``_robots_allowed`` check with a short per-host
cache.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from datasets.local_data.places_config import (
    _HEADERS,
    HTTP_TIMEOUT,
    MAX_RETRIES,
    ROBOTS_CACHE_TTL,
    _retry_delay,
    _robots_cache,
)
from pry.api.client import get_client

logger = logging.getLogger(__name__)


# ── HTTP with timeout + backoff ──────────────────────────────────────────
async def _http_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = MAX_RETRIES,
) -> httpx.Response | None:
    """GET with browser headers, timeouts, and exponential backoff.

    Retries on 429 (honoring Retry-After) and 5xx. Never raises: returns
    None on transport errors or after exhausting retries.
    """
    merged = dict(_HEADERS)
    if headers:
        merged.update(headers)
    client = await get_client()
    attempt = 0
    while True:
        try:
            resp = await client.get(
                url,
                params=params,
                headers=merged,
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            logger.warning("http_error", extra={"url": url, "error": str(exc)[:200]})
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt >= retries:
                logger.warning(
                    "http_retries_exhausted", extra={"url": url, "status": resp.status_code}
                )
                return None
            delay = _retry_delay(resp, attempt)
            logger.info(
                "http_backoff", extra={"url": url, "status": resp.status_code, "delay": delay}
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue
        return resp  # type: ignore[no-any-return]


# ── robots.txt (best-effort, fail-open) ──────────────────────────────────
async def _robots_allowed(url: str) -> bool:
    """Check robots.txt for ``url`` with a short per-host cache.

    Fails open (returns True) when robots.txt cannot be fetched or when
    ``PRY_LOCAL_RESPECT_ROBOTS`` is set to anything other than
    "1"/"true"/"yes"/"on". Reuses :func:`compliance.policy.check_robots_txt`.
    """
    if os.environ.get("PRY_LOCAL_RESPECT_ROBOTS", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    parsed = urlparse(url)
    key = f"{parsed.scheme}://{parsed.netloc}"
    now = time.monotonic()
    cached = _robots_cache.get(key)
    if cached and now - cached[0] < ROBOTS_CACHE_TTL:
        return cached[1]
    allowed = True
    try:
        from compliance.policy import check_robots_txt  # lazy: heavy import

        result = await check_robots_txt(url)
        allowed = bool(result.get("crawl_allowed", True))
        if not allowed:
            logger.warning(
                "robots_blocked",
                extra={"url": url, "matched": result.get("matched_disallow")},
            )
    except Exception as exc:  # noqa: BLE001 - fail open; never break on robots errors
        logger.warning("robots_check_failed", extra={"url": url, "error": str(exc)[:120]})
        allowed = True
    _robots_cache[key] = (now, allowed)
    return allowed
