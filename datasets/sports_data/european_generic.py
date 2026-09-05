"""Generic embedded/HTML European book fetchers (best-effort).

Extracted from :mod:`datasets.sports_data.european` — Betway, 10Bet,
SBOBet, Dafabet, 12Bet and W88. Several are JS-heavy or hard-geo-blocked,
and plain HTTP often returns no odds — that is flagged honestly via the
per-book health tracker.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

import httpx

import datasets.sports_data.offshore as offshore
from datasets.sports_data.european_common import (
    _EUROPEAN_SPORTS,
    EUROPEAN_BOOKS,
    _canonical_sport,
    _mark_book,
)
from datasets.sports_data.offshore import (
    _fetch_text_geo,
    _looks_blocked,
    _parse_decimal_rows,
    _parse_embedded_state,
)

logger = logging.getLogger(__name__)


def _generic_book_url(book: str, canonical: str) -> str | None:
    """Best-effort odds-page URL for a generic book; ``None`` when unsupported."""
    route = _EUROPEAN_SPORTS.get(canonical)
    if route is None:
        return None
    sport_slug, league = route
    base = EUROPEAN_BOOKS[book]["base_url"]
    # SBOBet uses bare sport paths (www.sbobet.com/tennis); the others append
    # an optional league segment.
    if book == "sbobet":
        return f"{base}/{sport_slug}"
    url = f"{base}/{sport_slug}"
    if league:
        url = f"{url}/{league}"
    return url


async def _fetch_generic_book(sport: str, book: str, limit: int) -> list[dict[str, Any]]:
    """Fetch a generic book: embedded state first, then decimal HTML rows."""
    start = offshore._monotonic()
    try:
        if book not in EUROPEAN_BOOKS:
            return []
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        url = _generic_book_url(book, canonical)
        if url is None:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        html = await _fetch_text_geo(url)
        if html is None:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if _looks_blocked(html):
            logger.warning("sports_european_blocked", extra={"book": book, "sport": sport})
            _mark_book(
                book,
                ok=False,
                blocked=True,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="anti-bot/geo block",
            )
            return []
        bookmaker = str(EUROPEAN_BOOKS[book]["title"])
        records = _parse_embedded_state(html, canonical, book, bookmaker)
        if not records:
            records = _parse_decimal_rows(html, canonical, book, bookmaker)
        for record in records:
            record["source"] = "european"
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(book, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": book, "sport": sport})
        _mark_book(
            book,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── Per-book fetchers (public) ──────────────────────────────────────────


async def fetch_betway(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Betway odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "betway", limit)


async def fetch_10bet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch 10Bet odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "10bet", limit)


async def fetch_sbobet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch SBOBet odds for one sport (best-effort; often geo-blocked)."""
    return await _fetch_generic_book(sport, "sbobet", limit)


async def fetch_dafabet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Dafabet odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "dafabet", limit)


async def fetch_12bet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch 12Bet odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "12bet", limit)


async def fetch_w88(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch W88 odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "w88", limit)
