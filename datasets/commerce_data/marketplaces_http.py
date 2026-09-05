"""HTTP fetch layer for the commerce marketplaces modules.

Bounded-retry GET with capped exponential backoff. The retry knobs
(``RETRY_BASE`` / ``MAX_BACKOFF`` / ``MAX_RETRIES``) are owned by the
:mod:`commerce_data.marketplaces` facade because tests monkeypatch them
there — they are read lazily at call time via :func:`_retry_knobs`.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _retry_knobs() -> tuple[float, float, int]:
    """Read the retry knobs from the facade module (late import).

    The facade owns these knobs because tests monkeypatch them on
    ``marketplaces``; a late import picks up patched values at call time.
    """
    from datasets.commerce_data.marketplaces import MAX_BACKOFF, MAX_RETRIES, RETRY_BASE

    return RETRY_BASE, MAX_BACKOFF, MAX_RETRIES


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (knobs are test-overridable)."""
    retry_base, max_backoff, _ = _retry_knobs()
    if attempt <= 0 or retry_base <= 0 or max_backoff <= 0:
        return
    await asyncio.sleep(min(max_backoff, retry_base * (2**attempt)))


async def _fetch(url: str, params: dict[str, str] | None = None) -> str:
    """GET a URL with bounded backoff retries; never raises ('' on failure)."""
    _, _, max_retries = _retry_knobs()
    last_error = ""
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.get(url, params=params)
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                return ""
            return resp.text
        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("commerce_fetch_failed", extra={"url": url[:120], "error": last_error})
    return ""
