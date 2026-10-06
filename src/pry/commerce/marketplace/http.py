"""Marketplace HTTP transport — UA rotation, retries, robots.txt honoring.
Never raises: every fetch returns ``None`` on failure. Retries with
exponential backoff on 429 (honoring Retry-After), 5xx and transport
errors; any other 4xx is a hard failure.
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
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from pry.api.client import get_client
from pry.commerce.marketplace.config import (
    HTTP_TIMEOUT,
    MAX_BACKOFF,
    RETRY_BASE,
    ROBOTS_TIMEOUT,
    _honor_robots,
    _http_retries,
    _rotate_ua,
)

logger = logging.getLogger(__name__)


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse the Retry-After header (seconds); None when absent/invalid."""
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        logger.warning("http_suppressed", exc_info=True)
        return None


def _backoff(attempt: int) -> float:
    """Exponential backoff with cap."""
    return min(RETRY_BASE * (2**attempt), MAX_BACKOFF)


async def _fetch_html(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
    follow_redirects: bool = True,
    request_timeout: httpx.Timeout = HTTP_TIMEOUT,
) -> str | None:
    """GET ``url`` and return the response text; None on any failure.
    Never raises. Rotates the User-Agent per attempt, retries with
    exponential backoff on 429 (honoring Retry-After), 5xx and transport
    errors, and treats any 4xx as a hard failure.
    """
    client = await get_client()
    attempts = retries if retries is not None else _http_retries()
    for attempt in range(attempts):
        try:
            request_headers = {"User-Agent": _rotate_ua()}
            if headers:
                request_headers.update(headers)
            resp = await client.get(
                url,
                params=params,
                headers=request_headers,
                timeout=request_timeout,
                follow_redirects=follow_redirects,
            )
        except httpx.HTTPError as exc:  # transport errors, timeouts
            logger.warning(
                "marketplace_http_error",
                extra={"url": url[:140], "error": str(exc)[:140], "attempt": attempt},
            )
            if attempt + 1 < attempts:
                await asyncio.sleep(_backoff(attempt))
            continue
        if resp.status_code == 429:
            if attempt + 1 < attempts:
                await asyncio.sleep(_retry_after_seconds(resp) or _backoff(attempt))
            continue
        if resp.status_code >= 500:
            if attempt + 1 < attempts:
                await asyncio.sleep(_backoff(attempt))
            continue
        if resp.status_code >= 400:
            return None
        if resp.status_code == 200:
            return resp.text
        return None
    return None


async def _fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
) -> Any:
    """GET ``url`` and return parsed JSON; None on any failure (never raises)."""
    text = await _fetch_html(url, params=params, headers=headers, retries=retries)
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        logger.warning("http_suppressed", exc_info=True)
        return None


# ── robots.txt honoring (Amazon only — spec: rotate UA, honor robots, backoff) ──
_ROBOTS_CACHE: dict[str, tuple[float, bool]] = {}
_ROBOTS_TTL = 3600.0  # seconds


def _robots_rules(text: str) -> tuple[list[str], list[str]]:
    """Parse robots.txt into (allow, disallow) path rules for our UA group."""
    allow: list[str] = []
    disallow: list[str] = []
    group = "*"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            group = value.lower() or "*"
        elif group in ("*", "prybot"):
            if key == "disallow":
                disallow.append(value)
            elif key == "allow":
                allow.append(value)
    return allow, disallow


def _rule_matches(rule: str, path: str) -> bool:
    """Match a robots rule (``*`` glob) against a URL path prefix."""
    if not rule:
        return False
    pattern = re.escape(rule).replace(r"\*", ".*")
    return re.search(f"^{pattern}", path) is not None


async def _fetch_robots(host: str, path: str) -> bool:
    """Fetch + evaluate robots.txt for one host/path; True (allow) by default."""
    allow: list[str] = []
    disallow: list[str] = []
    try:
        client = await get_client()
        resp = await client.get(
            f"https://{host}/robots.txt",
            headers={"User-Agent": "prybot/3.0"},
            timeout=ROBOTS_TIMEOUT,
            follow_redirects=False,
        )
        if resp.status_code == 200:
            allow, disallow = _robots_rules(resp.text)
    except httpx.HTTPError:
        logger.warning("http_suppressed", exc_info=True)
        # robots.txt unreachable → allow (standard convention)
    for rule in allow:
        if _rule_matches(rule, path):
            return True
    return not any(_rule_matches(rule, path) for rule in disallow)


async def _robots_allowed(url: str) -> bool:
    """True when robots.txt permits fetching ``url`` (cached per host)."""
    if not _honor_robots():
        return True
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        path = parts.path or "/"
    except ValueError:
        logger.warning("http_suppressed", exc_info=True)
        return True
    if not host:
        return True
    cached = _ROBOTS_CACHE.get(host)
    if cached and time.monotonic() - cached[0] < _ROBOTS_TTL:
        return cached[1]
    allowed = await _fetch_robots(host, path)
    _ROBOTS_CACHE[host] = (time.monotonic(), allowed)
    return allowed


def _clear_robots_cache() -> None:
    """Clear the robots.txt cache (used by tests)."""
    _ROBOTS_CACHE.clear()
