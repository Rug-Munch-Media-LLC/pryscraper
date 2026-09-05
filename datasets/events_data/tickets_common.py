"""Shared endpoints, configuration and low-level helpers for event tickets.

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
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# ── endpoints & configuration ──────────────────────────────────────────
_TM_SEARCH_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
_TM_EVENT_URL = "https://app.ticketmaster.com/discovery/v2/events/{event_id}.json"
_TM_SEARCH_PAGE_URL = "https://www.ticketmaster.com/search?q={q}"
_SG_SEARCH_URL = "https://seatgeek.com/search?q={q}"
_SH_SEARCH_URL = "https://www.stubhub.com/search?q={q}"

_TM_KEY_ENV = "PRY_TICKETMASTER_API_KEY"
_HISTORY_JSON_ENV = "PRY_TICKETS_HISTORY_JSON"

_MAX_LIMIT = 100  # Ticketmaster Discovery 'size' cap

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Backoff tuning (tests monkeypatch these on the ``tickets`` facade).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 1

_JSON_LD_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)


def _facade() -> Any:
    """Return the public ``tickets`` facade module (lazy, avoids circular import).

    Test-overridable knobs (``RETRY_BASE``, ``_tm_api_key``, ...) are patched
    on the facade module, so runtime code must read them from there.
    """
    from datasets.events_data import tickets

    return tickets


# ── low-level helpers ──────────────────────────────────────────────────


def _tm_api_key() -> str:
    """Return the configured Ticketmaster Discovery key, or '' when missing."""
    return os.environ.get(_TM_KEY_ENV, "").strip()


def _clamp_limit(limit: Any) -> int:
    """Coerce ``limit`` to an int within [1, _MAX_LIMIT]; default 20."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, _MAX_LIMIT))


def _url_quote(query: str) -> str:
    return quote(query, safe="")


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (knobs are test-overridable)."""
    facade = _facade()
    if attempt <= 0 or facade.RETRY_BASE <= 0 or facade.MAX_BACKOFF <= 0:
        return
    await asyncio.sleep(min(facade.MAX_BACKOFF, facade.RETRY_BASE * (2**attempt)))


async def _fetch(url: str, params: dict[str, str] | None = None) -> str:
    """GET a URL with bounded backoff retries; never raises ('' on failure)."""
    facade = _facade()
    last_error = ""
    for attempt in range(facade.MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.get(url, params=params)
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                return ""
            return resp.text
        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("events_fetch_failed", extra={"url": url[:120], "error": last_error})
    return ""


def _to_float(value: Any) -> float | None:
    """Coerce a JSON/text value to float; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _to_int(value: Any) -> int | None:
    """Coerce a JSON/text value to int; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _walk_dicts(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict (at any depth) inside a parsed JSON tree."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _parse_json_ld(raw: str) -> list[dict[str, Any]]:
    """Parse every JSON-LD block in an HTML page into dicts."""
    out: list[dict[str, Any]] = []
    for match in _JSON_LD_RE.finditer(raw):
        text = match.group(1).strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            out.append(data)
        elif isinstance(data, list):
            out.extend(item for item in data if isinstance(item, dict))
    return out
