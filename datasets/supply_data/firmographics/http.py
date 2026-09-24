"""Shared HTTP transport and retry policy for firmographics sources."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(15.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-firmo/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


async def _fetch_once(url: str) -> httpx.Response:
    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers=_HEADERS,
        follow_redirects=True,
    ) as client:
        return await client.get(url)


async def _fetch_html(url: str) -> str | None:
    """Fetch website HTML text, or ``None`` on any failure."""
    try:
        response = await async_retry(lambda: _fetch_once(url), config=_RETRY_CONFIG)
        if 200 <= response.status_code < 400:
            return response.text
    except (httpx.HTTPError, OSError):
        logger.debug("firmographics_website_fetch_failed", exc_info=True, extra={"url": url})
    return None


def configure_retries(config: RetryConfig) -> RetryConfig:
    """Replace the firmographics retry policy and return the previous value."""
    global _RETRY_CONFIG
    previous, _RETRY_CONFIG = _RETRY_CONFIG, config
    return previous
