"""HTTP transport for the docket sources (CourtListener / Justia / NY eCourts).

Shared request helpers: token-aware headers, retrying GET/POST wrappers that
degrade to ``None`` on failure, and the PACER docket-lookup fetch.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import os
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
_JUSTIA_BASE = "https://dockets.justia.com"
_PACER_FETCH_URL = f"{_BASE_URL}/pacer-fetch/"
_NY_ECOURTS_URL = "https://iapps.courts.state.ny.us/webcivil/FCASSearch"
_TIMEOUT = httpx.Timeout(15.0)
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

# Optional free token: https://www.courtlistener.com/accounts/register/
_API_KEY_ENV = "PRY_COURTLISTENER_API_KEY"


def _headers() -> dict[str, str]:
    """Base request headers plus the CourtListener token when configured."""
    token = os.environ.get(_API_KEY_ENV, "").strip()
    if token:
        return {**_HEADERS, "Authorization": f"Token {token}"}
    return dict(_HEADERS)


async def _fetch_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return the parsed JSON object, or ``None`` on failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("courtlistener payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_text(url: str, params: dict[str, Any] | None = None) -> str | None:
    """GET ``url`` and return the response text, or ``None`` on failure.

    Used by the Justia scrape path; HTML pages are returned as text and
    parsed with signature regexes (degrades to ``[]`` on layout changes).
    """

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


async def _fetch_json_post(url: str, body: dict[str, Any]) -> dict[str, Any] | None:
    """POST JSON ``body`` to ``url`` and return the parsed object, or ``None``.

    Used by the CourtListener ``pacer-fetch`` path (PACER docket lookup).
    """

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("courtlistener pacer-fetch payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_text_post(url: str, data: dict[str, str]) -> str | None:
    """POST form-encoded ``data`` to ``url`` and return the response text.

    Used by the NY eCourts scrape path; HTML pages are returned as text and
    parsed with signature regexes (degrades to ``None`` on failure).
    """

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            response = await client.post(url, data=data)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


async def _fetch_pacer_docket(docket_id: int) -> dict[str, Any] | None:
    """POST to CourtListener's ``pacer-fetch`` endpoint (PACER docket lookup).

    Triggers a PACER fetch for a CourtListener ``docket_id`` that is missing
    from the RECAP archive. Requires the free API token with the
    ``pacer_fetch`` permission; degrades to ``None`` on failure.
    """
    return await _fetch_json_post(_PACER_FETCH_URL, {"docket_id": docket_id})


def configure_retries(config: RetryConfig) -> RetryConfig:
    """Replace the docket retry policy and return the previous policy."""
    global _RETRY_CONFIG
    previous, _RETRY_CONFIG = _RETRY_CONFIG, config
    return previous
