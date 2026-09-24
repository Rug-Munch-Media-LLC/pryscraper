"""HTTP transport and retry policy for SEC EDGAR requests."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pryscraper-legal/1.0; +https://git.rugmunch.io/RugMunchMedia/pryscraper)",
    "Accept": "application/json",
}
logger = logging.getLogger(__name__)


async def _fetch_json(url: str, params: dict[str, Any] | None = None) -> Any:
    """Return parsed JSON, or ``None`` when the request or payload fails."""

    async def _one() -> Any:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        logger.debug("sec_fetch_failed", exc_info=True, extra={"url": url})
        return None


def configure_retries(config: RetryConfig) -> RetryConfig:
    """Replace the EDGAR retry policy and return the previous policy."""
    global _RETRY_CONFIG
    previous, _RETRY_CONFIG = _RETRY_CONFIG, config
    return previous
