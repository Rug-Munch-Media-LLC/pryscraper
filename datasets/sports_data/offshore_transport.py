"""Geo-aware HTTP transport for offshore sportsbook fetchers.

Wraps the shared ``sources._fetch_text`` (stealth headers, retry, TTL
cache) with a Webshare residential-proxy fallback: when a book's direct
request looks like an anti-bot / geo block and ``WEBSHARE_PROXY_LIST`` is
configured, one more attempt is made through the pool. The blocked body is
surfaced to the caller when no proxy is available (or the proxy is also
blocked) so blocks are flagged honestly — never silently treated as
"no odds". Never raises.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

import datasets.sports_data.sources as sources
from datasets.sports_data.sources import _fetch_text, _looks_blocked
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)


def _retry_config() -> RetryConfig:
    """Retry config, resolved through the facade module at call time.

    Kept indirect so tests can monkeypatch ``offshore._RETRY_CONFIG`` (the
    facade re-exports this module's default) — same pattern as the sibling
    registry lookup in ``european_common``.
    """
    from datasets.sports_data.offshore import _RETRY_CONFIG

    return _RETRY_CONFIG


def _next_proxy() -> str | None:
    """Webshare proxy getter, resolved through the facade module at call time.

    Indirect so tests can monkeypatch ``offshore.next_webshare_proxy``.
    """
    from datasets.sports_data.offshore import next_webshare_proxy

    return next_webshare_proxy()


async def _fetch_text_geo(url: str) -> str | None:
    """Fetch text; on block/transport failure retry via a Webshare proxy.

    Uses the repo's shared ``sources._fetch_text`` (stealth headers, retry,
    TTL cache) for the direct attempt. When the direct response looks like an
    anti-bot/geo block and a proxy is configured (``WEBSHARE_PROXY_LIST``),
    one more attempt is made through the pool. The blocked body is surfaced
    to the caller when no proxy is available (or the proxy is also blocked)
    so blocks are flagged honestly — never silently treated as "no odds".
    Never raises.
    """

    async def _via_proxy(proxy: str) -> str | None:
        async def _one() -> str:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                headers=sources._stealth_headers(url),
                proxy=proxy,
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
                if response.status_code >= 500:
                    response.raise_for_status()
                text = response.text
            if not text:
                raise ValueError("empty proxied upstream response")
            return text

        try:
            payload = await async_retry(_one, config=_retry_config())
        except (httpx.HTTPError, OSError, ValueError):
            return None
        if payload is None or _looks_blocked(payload):
            return None
        return payload

    direct = await _fetch_text(url)
    if direct is not None and not _looks_blocked(direct):
        return direct
    proxy = _next_proxy()
    if proxy is None:
        # No proxy configured: surface the blocked body (or None on a pure
        # transport failure) so callers can flag the block honestly.
        return direct
    proxied = await _via_proxy(proxy)
    if proxied is not None:
        return proxied
    return direct


async def _fetch_json_geo(url: str) -> Any | None:
    """GET ``url`` (proxy fallback on geo-block) and parse JSON; ``None`` on failure."""
    text = await _fetch_text_geo(url)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
