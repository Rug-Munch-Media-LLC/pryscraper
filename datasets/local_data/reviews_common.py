"""Shared helpers for review extraction (HTTP, robots, caching, coercion).

Used by :mod:`datasets.local_data.reviews_google` and
:mod:`datasets.local_data.reviews_yelp`.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from pry.api.client import get_client

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
MAX_RETRIES = 3
RETRY_BASE = 0.8
MAX_BACKOFF = 6.0
RESULT_CACHE_TTL = 30.0  # in-memory result cache TTL (seconds)
ROBOTS_CACHE_TTL = 300.0  # robots.txt per-host cache TTL (seconds)

# Browser-ish headers: both Google Maps and Yelp serve the JS page (with
# embedded JSON) to normal user agents; a bare "pry/3.0" UA gets the no-JS
# shell.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_ANTI_BOT_SIGNALS = (
    "unusual traffic",
    "unusual activity",
    "are you a robot",
    "enable javascript",
    "not a robot",
    "recaptcha",
    "captcha",
    "consent.google.com",
)

_WS_RE = re.compile(r"\s+")
_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|[a-z]{3,9}\s+\d{1,2},?\s+\d{4}|"
    r"\d+\s+(year|month|week|day|hour)s?\s+ago)",
    re.IGNORECASE,
)

_cache: dict[str, tuple[float, Any]] = {}
_robots_cache: dict[str, tuple[float, bool]] = {}


def _clear_cache() -> None:
    """Clear all in-memory caches (used by tests)."""
    _cache.clear()
    _robots_cache.clear()


# ── Small coercion helpers ───────────────────────────────────────────────
def _opt_float(value: Any) -> float | None:
    """Coerce a value to float; None on any failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    """Collapse whitespace + unescape HTML entities; "" for empty input."""
    return html.unescape(_WS_RE.sub(" ", str(value or "")).strip())


def _normalize_date(value: str) -> str:
    """Trim an ISO datetime ("2024-03-15 10:00:00") to its date part."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", value.strip())
    return m.group(1) if m else value.strip()


def _env_int(name: str, default: int) -> int:
    """Parse an env var as a positive int; ``default`` on failure."""
    raw = os.environ.get(name, "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _cache_get(key: str) -> Any | None:
    """Return a cached value, or None when expired/missing."""
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > RESULT_CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    """Store a value under ``key``."""
    _cache[key] = (time.monotonic(), value)


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    """Exponential backoff, honoring Retry-After when present."""
    if resp is not None:
        raw = resp.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), MAX_BACKOFF)
            except ValueError:
                pass  # malformed Retry-After header — fall back to default backoff
    return min(RETRY_BASE * (2**attempt), MAX_BACKOFF)


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
        return resp


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


def _is_anti_bot(html_text: str) -> bool:
    """Detect consent/captcha/"unusual traffic" walls in the first 300 KB."""
    low = html_text[:300_000].lower()
    return any(sig in low for sig in _ANTI_BOT_SIGNALS)


# ── Shared nested walker ─────────────────────────────────────────────────
def _iter_dicts(obj: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Yield nested dict values up to ``depth``."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item, depth + 1)
