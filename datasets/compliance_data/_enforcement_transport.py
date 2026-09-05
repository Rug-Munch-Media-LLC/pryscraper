"""HTTP transport for the enforcement sources (``compliance_data``).

Thin JSON/HTML fetchers with the retry policy injected by the thin loader
(``enforcement.py``) via :func:`bind_retry` so the retry policy stays
patchable in one place.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from datasets.compliance_data._enforcement_data import (
    _HEADERS,
    _HTML_HEADERS,
    _RETRY_CONFIG,
    _TIMEOUT,
)
from pry.engine.retry import RetryConfig, async_retry

if TYPE_CHECKING:
    from collections.abc import Callable

# The thin loader binds a retry-config getter so tests can patch
# ``enforcement._RETRY_CONFIG`` and the transport picks it up at call time.
_retry_config_getter: Callable[[], RetryConfig] | None = None


def bind_retry(getter: Callable[[], RetryConfig]) -> None:
    """Wire the thin loader's (patchable) retry config into the transport."""
    global _retry_config_getter
    _retry_config_getter = getter


def _get_retry_config() -> RetryConfig:
    return _retry_config_getter() if _retry_config_getter else _RETRY_CONFIG


# ── Fetching ──────────────────────────────────────────────────────────
async def _fetch_json(url: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return the parsed JSON object, or ``None`` on failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("enforcement API payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_get_retry_config())
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_html(url: str, params: dict[str, str] | None = None) -> str | None:
    """GET ``url`` and return the response text, or ``None`` on failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HTML_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            text = response.text
        if not text:
            raise ValueError("enforcement page payload is empty")
        return text

    try:
        return await async_retry(_one, config=_get_retry_config())
    except (httpx.HTTPError, OSError, ValueError):
        return None
