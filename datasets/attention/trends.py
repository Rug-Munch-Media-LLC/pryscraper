"""Pry — Google Trends interest via Google's internal (public, keyless) JSON API.

``pytrends`` is not installed, so this module implements the same flow
that pytrends wraps, directly against Google's public trends endpoints:

1. ``GET /trends/api/explore`` with a JSON ``req`` — returns "widgets"
   describing the timeseries and related-query panels (plus tokens).
2. ``GET /trends/api/widgetdata/multiline/json`` — the interest timeline.
3. ``GET /trends/api/widgetdata/relatedsearches/json`` — related queries.

Responses carry Google's ``)]}'`` XSSI prefix which is stripped before
JSON parsing. A single httpx client is used per call so the ``NID``
cookie set by the explore request persists to the widget requests.

Contract:
    >>> result = await trend_interest("bitcoin", timeframe="today 12-m")
    >>> result["timeline"]  # [{"date": "2026-08-16", "value": 100}, ...]
    >>> result["related"]   # [{"query": "btc price", "value": 100}, ...]

Robustness:
    * never raises — any failure yields ``{"keyword", "timeline": [],
      "related": []}`` plus an ``error`` key
    * capped exponential backoff on 429 / transport errors
    * per-request timeouts on the shared httpx client

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://trends.google.com/trends/api"
_HL = "en-US"
_TZ = "0"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json,text/plain,*/*",
}

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 2


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (never raises)."""
    await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))


def _strip_prefix(text: str) -> str:
    """Remove Google's ``)]}'`` XSSI prefix before JSON parsing."""
    if text.startswith(")]}'"):
        text = text[4:]
    return text.lstrip()


def _format_date(raw: Any) -> str:
    """Normalize a trends date field to ``YYYY-MM-DD``.

    The multiline endpoint returns epoch milliseconds (int); the explore
    payload echoes the original ``YYYY-MM-DD`` string. Anything else is
    stringified untouched.
    """
    if isinstance(raw, (int, float)):
        ms = int(raw)
        try:
            return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return str(raw)
    return str(raw or "")


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, str]) -> Any:
    """GET + strip XSSI prefix + JSON parse, with backoff. Never raises; None on failure."""
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.get(url, params=params, timeout=_TIMEOUT)
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                return None
            return json.loads(_strip_prefix(resp.text))
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("trends_get_json_failed", extra={"url": url[:80], "error": last_error})
    return None


async def _explore_widgets(
    client: httpx.AsyncClient, keyword: str, timeframe: str
) -> list[dict[str, Any]]:
    """Fetch the widget descriptors (timeseries + related) for a keyword."""
    req = {
        "comparisonItem": [{"keyword": keyword, "geo": "", "time": timeframe}],
        "category": 0,
        "property": "",
    }
    params = {"hl": _HL, "tz": _TZ, "req": json.dumps(req, separators=(",", ":"))}
    data = await _get_json(client, f"{_BASE}/explore", params)
    if not isinstance(data, dict):
        return []
    widgets = data.get("widgets") or []
    return [w for w in widgets if isinstance(w, dict)]


async def _fetch_timeseries(
    client: httpx.AsyncClient, widget: dict[str, Any]
) -> list[dict[str, Any]]:
    """Fetch the interest-over-time timeline from a TIMESERIES widget."""
    req = widget.get("request")
    token = widget.get("token")
    if not req or not token:
        return []
    params = {
        "hl": _HL,
        "tz": _TZ,
        "req": json.dumps(req, separators=(",", ":")),
        "token": str(token),
    }
    data = await _get_json(client, f"{_BASE}/widgetdata/multiline/json", params)
    if not isinstance(data, dict):
        return []
    timeline: list[dict[str, Any]] = []
    for item in data.get("timelineData") or []:
        if not isinstance(item, dict):
            continue
        values = item.get("value") or []
        value = 0
        if values and isinstance(values[0], (int, float)):
            value = int(values[0])
        # The API emits the bucket under the "time" key: epoch-ms int on
        # the live multiline endpoint, or the original YYYY-MM-DD string on
        # the explore-echo path. _format_date normalizes both.
        timeline.append({"date": _format_date(item.get("time")), "value": value})
    return timeline


async def _fetch_related(client: httpx.AsyncClient, widget: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch related queries from a RELATED_QUERIES widget."""
    req = widget.get("request")
    token = widget.get("token")
    if not req or not token:
        return []
    params = {
        "hl": _HL,
        "tz": _TZ,
        "req": json.dumps(req, separators=(",", ":")),
        "token": str(token),
    }
    data = await _get_json(client, f"{_BASE}/widgetdata/relatedsearches/json", params)
    if not isinstance(data, dict):
        return []
    ranked = data.get("rankedList") or []
    if not ranked or not isinstance(ranked[0], dict):
        return []
    related: list[dict[str, Any]] = []
    for kw in ranked[0].get("rankedKeyword") or []:
        if not isinstance(kw, dict):
            continue
        query = kw.get("query")
        if query:
            related.append({"query": query, "value": kw.get("value", 0)})
    return related


async def trend_interest(keyword: str, timeframe: str = "today 12-m") -> dict[str, Any]:
    """Return Google Trends interest timeline + related queries for a keyword.

    Never raises. On failure returns the full shape with empty lists and
    an ``error`` key.
    """
    if not keyword or not keyword.strip():
        return {
            "keyword": keyword,
            "timeframe": timeframe,
            "timeline": [],
            "related": [],
            "error": "empty keyword",
        }
    try:
        # Dedicated client per call so the explore NID cookie persists to
        # the widget requests (no cross-call cookie pollution).
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            widgets = await _explore_widgets(client, keyword.strip(), timeframe)
            if not widgets:
                return {
                    "keyword": keyword,
                    "timeframe": timeframe,
                    "timeline": [],
                    "related": [],
                    "error": "no widgets",
                }
            timeline: list[dict[str, Any]] = []
            related: list[dict[str, Any]] = []
            for widget in widgets:
                widget_id = widget.get("id", "")
                if widget_id == "TIMESERIES":
                    timeline = await _fetch_timeseries(client, widget)
                elif widget_id == "RELATED_QUERIES":
                    related = await _fetch_related(client, widget)
            return {
                "keyword": keyword,
                "timeframe": timeframe,
                "timeline": timeline,
                "related": related,
            }
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "trend_interest_failed",
            extra={"keyword": keyword[:80], "error": str(exc)[:200]},
        )
        return {
            "keyword": keyword,
            "timeframe": timeframe,
            "timeline": [],
            "related": [],
            "error": str(exc)[:200],
        }
