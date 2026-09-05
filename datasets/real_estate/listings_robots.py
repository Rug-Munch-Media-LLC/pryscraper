"""Real-estate listings — robots.txt policy + shared HTTP layer.

Every real-estate source fetch goes through :func:`_fetch_page` (or the
Redfin JSONP fetcher in :mod:`listings_redfin`), which honors a per-host
robots.txt check (cached in-process) and the robots ``Crawl-delay``,
mirroring :mod:`compliance`'s treatment of robots.txt as an advisory
signal: the disallow is logged and surfaced on the result rather than
silently ignored. Set ``PRY_REAL_ESTATE_ENFORCE_ROBOTS=1`` to hard-block
disallowed paths (returns empty instead of fetching). The robots
``Crawl-delay`` is honored (capped at 3s; override with
``PRY_REAL_ESTATE_CRAWL_DELAY``, ``0`` disables).

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
import json
import logging
import os
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(12.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── robots.txt policy ──────────────────────────────────────────────────
_ENFORCE_ROBOTS_ENV = "PRY_REAL_ESTATE_ENFORCE_ROBOTS"
_CRAWL_DELAY_ENV = "PRY_REAL_ESTATE_CRAWL_DELAY"
_ROBOTS_CRAWL_DELAY_CAP = 3.0

# Per-host parsed robots.txt (RobotFileParser instances), cached for the
# process lifetime. A failed robots fetch is cached as ``None`` so we never
# block data extraction on robots infrastructure problems (same posture as
# compliance.policy.check_robots_txt: 404 / error => no restrictions).
_robots_cache: dict[str, RobotFileParser | None] = {}

# The last crawl-delay declared for a host, read back by the sleeper.
_crawl_delay_cache: dict[str, float] = {}


def _robots_enforced() -> bool:
    """True when disallowed paths must be hard-blocked (env override)."""
    return os.environ.get(_ENFORCE_ROBOTS_ENV, "0") == "1"


def _crawl_delay_override() -> float | None:
    """Env override for crawl-delay (``0`` disables sleeping)."""
    raw = os.environ.get(_CRAWL_DELAY_ENV)
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


async def _robots_for_host(host: str) -> RobotFileParser | None:
    """Fetch + parse robots.txt for a host once; cached per process."""
    if host in _robots_cache:
        return _robots_cache[host]
    robots_url = f"https://{host}/robots.txt"
    parsed = RobotFileParser()
    parsed.set_url(robots_url)
    parser: RobotFileParser | None = parsed
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), headers=_HEADERS) as client:
            response = await client.get(robots_url)
        if response.status_code == 200 and response.text:
            parsed.parse(response.text.splitlines())
            delay = parsed.crawl_delay("*") or parsed.crawl_delay("pry") or 0.0
            _crawl_delay_cache[host] = float(delay)
        else:
            parser = None  # no robots.txt => no restrictions (404/error)
    except (httpx.HTTPError, OSError):
        parser = None
    _robots_cache[host] = parser
    return parser


async def _robots_allowed(url: str) -> bool:
    """Best-effort robots.txt verdict for ``url`` (True when unknown)."""
    host = urlparse(url).netloc
    parser = await _robots_for_host(host)
    if parser is None:
        return True
    return parser.can_fetch("*", url) or parser.can_fetch("pry", url)


async def _sleep_for_robots(url: str) -> None:
    """Honor the robots ``Crawl-delay`` for the host (capped, tunable)."""
    host = urlparse(url).netloc
    delay = _crawl_delay_override()
    if delay is None:
        delay = min(_crawl_delay_cache.get(host, 0.0), _ROBOTS_CRAWL_DELAY_CAP)
    if delay > 0:
        await asyncio.sleep(delay)


# ── HTTP layer ─────────────────────────────────────────────────────────
async def _fetch_page(url: str) -> str | None:
    """GET a page honoring robots + backoff; ``None`` on failure/block."""
    if not await _robots_allowed(url):
        if _robots_enforced():
            logger.warning("real_estate_robots_blocked", extra={"url": url})
            return None
        logger.warning("real_estate_robots_disallowed_fetching", extra={"url": url})
    await _sleep_for_robots(url)

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code} for {url}",
                    request=response.request,
                    response=response,
                )
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


def _redfin_jsonp_payload(raw: str) -> dict[str, Any]:
    """Decode a Redfin ``{}&&{...}`` JSONP wrapper into a dict."""
    if raw.lstrip().startswith("{}&&"):
        raw = raw.lstrip()[4:]
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("redfin payload is not an object")
    return payload


# ── Test/utility hooks ─────────────────────────────────────────────────
def reset_robots_cache() -> None:
    """Drop the in-process robots.txt + crawl-delay caches (tests/tooling)."""
    _robots_cache.clear()
    _crawl_delay_cache.clear()
