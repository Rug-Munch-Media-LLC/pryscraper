"""Pry — travel flights: Google Flights scraping (no public API).

Google Flights has no public search API, so this module drives the public
search deep-link page directly:

1. Encode the search (origin, destination, date) into the ``tfs`` query
   parameter — a Base64-encoded protobuf payload (see ``flights_tfs``).
2. GET ``https://www.google.com/travel/flights/flights`` with that ``tfs``.
3. Extract the ``AF_initDataCallback({...})`` JSON payloads embedded in the
   page and locate flight-option-like records with a defensive signature
   search (see ``flights_parse``), because the exact array layout drifts
   frequently.

Contract
--------
* async, never raise
* ``search_flights(origin, dest, date, limit=20) -> list[dict]`` where each
  entry is ``{"date", "price", "airline", "duration", "stops"}`` — price in
  USD (int), duration in minutes (int), stops int (0 = nonstop). Sorted by
  price ascending.
* ``cheapest_date_grid(origin, dest, start_date, end_date) -> list[dict]`` —
  the cheapest option per day, same entry shape, sorted by date ascending.
  Days whose page could not be fetched/parsed are omitted.

Reliability (read before shipping)
----------------------------------
The embedded ``AF_initDataCallback`` JSON on Google Flights is an
unversioned, frequently-changing internal format. Extraction is
signature-based and best-effort: when the layout shifts, results silently
degrade to ``[]`` (never an exception). Google also rate-limits aggressive
page hits — keep grids bounded (``_MAX_GRID_DAYS``, default 30) and respect
the backoff knobs. Treat every result as a best-effort estimate.

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
import logging
from typing import Any

import httpx

from datasets.travel.flights_common import (
    _MAX_GRID_DAYS,  # noqa: F401  (re-exported for tests/back-compat)
    _MAX_RESULTS,
    _date_range,
    _normalize_code,
    _valid_date,
)
from datasets.travel.flights_parse import (
    _extract_af_callbacks,
    _extract_duration,  # noqa: F401  (re-exported for tests/back-compat)
    _extract_stops,  # noqa: F401  (re-exported for tests/back-compat)
    _find_flight_options,
)
from datasets.travel.flights_tfs import _build_tfs

__all__ = ["cheapest_date_grid", "search_flights"]

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.google.com/travel/flights/flights"
_CURRENCY = "USD"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 2

# Grid concurrency: max parallel per-day fetches in cheapest_date_grid.
_GRID_CONCURRENCY = 4


# ── HTTP layer ─────────────────────────────────────────────────────────
async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (never raises)."""
    await asyncio.sleep(min(RETRY_BASE * (2**attempt), MAX_BACKOFF))


async def _fetch_page(tfs: str) -> str:
    """Fetch the Google Flights deep-link page HTML (never raises)."""
    params = {"hl": "en", "curr": _CURRENCY, "tfs": tfs}
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.get(_SEARCH_URL, params=params)
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
    logger.warning("flights_fetch_failed", extra={"error": last_error})
    return ""


# ── public API ─────────────────────────────────────────────────────────
async def search_flights(
    origin: str, dest: str, date: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Search Google Flights for one-way options on ``date``.

    Args:
        origin: 3-letter IATA origin airport code (e.g. ``JFK``).
        dest: 3-letter IATA destination airport code (e.g. ``CDG``).
        date: Departure date as ``YYYY-MM-DD``.
        limit: Max results (clamped to 1..200).

    Returns:
        List of ``{"date", "price", "airline", "duration", "stops"}`` dicts
        sorted by price ascending. Empty list on any failure.
    """
    origin_code = _normalize_code(origin)
    dest_code = _normalize_code(dest)
    if not origin_code or not dest_code or not _valid_date(date):
        return []
    try:
        tfs = _build_tfs([(date, origin_code, dest_code)])
    except (TypeError, ValueError, UnicodeEncodeError):
        return []
    html = await _fetch_page(tfs)
    if not html:
        return []
    options: list[dict[str, Any]] = []
    for callback in _extract_af_callbacks(html):
        options.extend(_find_flight_options(callback.get("data")))
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int, int]] = set()
    for option in options:
        key = (option["price"], option["airline"], option["duration"], option["stops"])
        if key in seen:
            continue
        seen.add(key)
        results.append({"date": date, **option})
    return results[: max(1, min(limit, _MAX_RESULTS))]


async def cheapest_date_grid(
    origin: str, dest: str, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    """Cheapest flight per day between ``start_date`` and ``end_date``.

    Args:
        origin: 3-letter IATA origin airport code.
        dest: 3-letter IATA destination airport code.
        start_date: First date as ``YYYY-MM-DD``.
        end_date: Last date as ``YYYY-MM-DD`` (bounded to 30 days).

    Returns:
        One ``{"date", "price", "airline", "duration", "stops"}`` per day
        (the cheapest option), sorted by date ascending. Days whose page
        could not be fetched/parsed are omitted.
    """
    origin_code = _normalize_code(origin)
    dest_code = _normalize_code(dest)
    dates = _date_range(start_date, end_date)
    if not origin_code or not dest_code or not dates:
        return []

    semaphore = asyncio.Semaphore(_GRID_CONCURRENCY)

    async def _cheapest_for(day: str) -> dict[str, Any] | None:
        async with semaphore:
            flights = await search_flights(origin_code, dest_code, day, limit=5)
        if not flights:
            return None
        # Defensive: the source is expected to sort by price, but pick the
        # true minimum explicitly so ordering drift cannot leak through.
        return min(flights, key=lambda entry: entry["price"])

    rows = await asyncio.gather(*(_cheapest_for(day) for day in dates))
    cheapest = [row for row in rows if row is not None]
    cheapest.sort(key=lambda row: row["date"])
    return cheapest
