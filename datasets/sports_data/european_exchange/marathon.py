"""Marathonbet server-rendered coupon fetcher."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

import httpx

import datasets.sports_data.offshore as offshore
from datasets.sports_data.european_common import (
    _MARATHON_SPORTS,
    EUROPEAN_BOOKS,
    _canonical_sport,
    _mark_book,
)
from datasets.sports_data.european_exchange.common import logger
from datasets.sports_data.offshore import (
    _fetch_text_geo,
    _looks_blocked,
    _parse_decimal_rows,
)


async def fetch_marathonbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Marathonbet odds for one sport from the coupon pages.

    Marathonbet serves decimal-odds HTML rows (``coupon-row``) with the
    three-way (soccer) or two-way (NBA) layout; parsed by the generic
    decimal-rows parser shared with the offshore module.
    """
    name = "marathonbet"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        path = _MARATHON_SPORTS.get(canonical)
        if path is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        url = f"{EUROPEAN_BOOKS[name]['base_url']}/{path}/"
        html = await _fetch_text_geo(url)
        if html is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if _looks_blocked(html):
            _mark_book(
                name,
                ok=False,
                blocked=True,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="anti-bot/geo block",
            )
            return []
        records = _parse_decimal_rows(html, canonical, name, "Marathonbet")
        for record in records:
            record["source"] = "european"
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []
