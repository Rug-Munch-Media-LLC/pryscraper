"""Shared HTTP layer for crypto_market providers.

One httpx client (from ``pry.api.client``) with per-request timeouts and
exponential backoff with Retry-After support on 429 / 5xx / transport
errors. All failure modes return ``None`` / ``""`` so callers never see
an exception.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from pry.api.client import get_client

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=10.0, pool=8.0)
MAX_BACKOFF = 5.0  # cap for rate-limit sleeps (seconds)
RETRY_BASE = 1.0  # base delay for exponential backoff


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse the Retry-After header (seconds) if present."""
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


async def _get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 2,
) -> Any:
    """GET ``url`` and return parsed JSON; None on any failure.

    Retries with exponential backoff on 429 (honoring Retry-After), 5xx,
    and transport errors. All failure modes return None so callers never
    see an exception.
    """
    client = await get_client()
    for attempt in range(retries):
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
            if resp.status_code == 429:
                retry_after = _retry_after_seconds(resp)
                delay = retry_after if retry_after is not None else RETRY_BASE * (2**attempt)
                await asyncio.sleep(min(delay, MAX_BACKOFF))
                continue
            if resp.status_code >= 500:
                await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))
                continue
            if not resp.is_success:
                return None
            return resp.json()
        except httpx.HTTPError as exc:  # transport errors, timeouts, 4xx-as-error
            logger.warning(
                "crypto_market_http_error",
                extra={"url": url[:120], "error": str(exc)[:120], "attempt": attempt},
            )
            await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "crypto_market_bad_json",
                extra={"url": url[:120], "error": str(exc)[:120]},
            )
            return None
    return None


async def _get_text(url: str, *, params: dict[str, Any] | None = None) -> str:
    """GET ``url`` and return the response text; "" on any failure."""
    client = await get_client()
    try:
        resp = await client.get(url, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as exc:
        logger.warning(
            "crypto_market_http_text_error",
            extra={"url": url[:120], "error": str(exc)[:120]},
        )
        return ""


__all__ = [
    "HTTP_TIMEOUT",
    "MAX_BACKOFF",
    "RETRY_BASE",
    "_get_json",
    "_get_text",
    "_retry_after_seconds",
]
