"""Pry — plain-HTTP SERP fetch with a capped exponential-backoff budget."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import logging

import httpx

from .config import (
    _HEADERS,
    _MAX_NUM,
    _SERP_URL,
    _TIMEOUT,
    MAX_BACKOFF,
    MAX_RETRIES,
    RETRY_BASE,
)

logger = logging.getLogger(__name__)


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (never raises)."""
    await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))


def _serp_params(query: str, num: int) -> dict[str, str]:
    """Query-string parameters for one SERP request (num clamped 1..100)."""
    return {
        "q": query,
        "num": str(min(max(num, 1), _MAX_NUM)),
        "hl": "en",
        "gl": "us",
        "pws": "0",
    }


async def _fetch_serp(query: str, num: int) -> str:
    """Fetch the SERP HTML with capped exponential backoff (never raises)."""
    from pry.api.client import get_client

    client = await get_client()
    params = _serp_params(query, num)
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
