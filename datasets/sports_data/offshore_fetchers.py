"""Per-book offshore fetch pipeline and public per-book fetchers.

Builds each book's odds-page URL from the registry routing table, fetches
through the geo-aware transport, parses with the BetOnline-family parsers
(reused from :mod:`sports_data.sources`) or the generic offshore parsers,
and records per-book health. The public ``fetch_<book>()`` fetchers and the
:func:`fetch_offshore_odds` aggregator live here; every fetcher never
raises — it returns ``[]`` on any failure so one dead book never affects
the others.

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

import datasets.sports_data.sources as sources
from datasets.sports_data.offshore_books import (
    _BETONLINE_FAMILY,
    _OFFSHORE_SPORTS,
    _SPORTS,
    OFFSHORE_BOOK_ORDER,
    OFFSHORE_BOOKS,
    _mark_book,
    _resolve_sports,
)
from datasets.sports_data.offshore_parsers import _parse_decimal_rows, _parse_embedded_state
from datasets.sports_data.offshore_transport import _fetch_text_geo
from datasets.sports_data.sources import (
    _looks_blocked,
    _monotonic,
    _parse_betonline_embedded_json,
    _parse_betonline_html,
)

logger = logging.getLogger(__name__)


def _canonical_sport(sport: str) -> str | None:
    """Resolve a sport alias to the canonical odds key, or ``None``."""
    if _resolve_sports is None:
        return None
    slugs = _resolve_sports(sport)
    if not slugs:
        return None
    return _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key


def _book_url(book: str, sport: str) -> str | None:
    """Build the odds-page URL for one book/sport; ``None`` when unsupported."""
    route = _OFFSHORE_SPORTS.get(sport)
    if route is None:
        return None
    sport_slug, league = route
    url = f"{OFFSHORE_BOOKS[book]['base_url']}/{sport_slug}"
    if league:
        url = f"{url}/{league}"
    return url


async def _fetch_book(sport: str, book: str, limit: int) -> list[dict[str, Any]]:
    """Fetch one book's odds for one sport. Never raises — returns ``[]``."""
    start = _monotonic()
    try:
        if book not in OFFSHORE_BOOKS:
            return []
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        url = _book_url(book, canonical)
        if url is None:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        html = await _fetch_text_geo(url)
        if html is None:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if _looks_blocked(html):
            logger.warning("sports_offshore_blocked", extra={"book": book, "sport": sport})
            _mark_book(
                book,
                ok=False,
                blocked=True,
                latency_ms=int((_monotonic() - start) * 1000),
                error="anti-bot/geo block",
            )
            return []
        cfg = OFFSHORE_BOOKS[book]
        bookmaker = str(cfg["title"])
        if book in _BETONLINE_FAMILY:
            # Same platform as BetOnline: reuse its parsers directly.
            records = _parse_betonline_embedded_json(html, canonical)
            if not records:
                records = _parse_betonline_html(html, canonical)
            for record in records:
                record["book"] = book
                record["bookmaker"] = bookmaker
                record["source"] = "offshore"
        else:
            records = _parse_embedded_state(html, canonical, book, bookmaker)
            if not records:
                records = _parse_decimal_rows(html, canonical, book, bookmaker)
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(book, ok=True, latency_ms=int((_monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_offshore_failed", extra={"book": book, "sport": sport})
        _mark_book(
            book,
            ok=False,
            latency_ms=int((_monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── Per-book fetchers (public) ──────────────────────────────────────────


async def fetch_bookmaker(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BookMaker odds for one sport (offshore BookMaker-group book)."""
    return await _fetch_book(sport, "bookmaker", limit)


async def fetch_heritage(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Heritage odds for one sport (offshore; JS-heavy, best-effort)."""
    return await _fetch_book(sport, "heritage", limit)


async def fetch_mybookie(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch MyBookie odds for one sport (offshore; JS-heavy, best-effort)."""
    return await _fetch_book(sport, "mybookie", limit)


async def fetch_betus(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BetUS odds for one sport (offshore; JS-heavy, best-effort)."""
    return await _fetch_book(sport, "betus", limit)


async def fetch_jazzsports(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch JazzSports odds for one sport (offshore; JS-heavy, best-effort)."""
    return await _fetch_book(sport, "jazzsports", limit)


async def fetch_sportsbetting(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch SportsBetting.ag odds for one sport (BookMaker-group brand)."""
    return await _fetch_book(sport, "sportsbetting", limit)


async def fetch_betanysports(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BetAnySports odds for one sport (BookMaker-group brand)."""
    return await _fetch_book(sport, "betanysports", limit)


async def fetch_wagerweb(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch WagerWeb odds for one sport (BookMaker-group brand)."""
    return await _fetch_book(sport, "wagerweb", limit)


async def fetch_nitrobetting(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch NitroBetting odds for one sport (crypto book; best-effort)."""
    return await _fetch_book(sport, "nitrobetting", limit)


async def fetch_lowvig(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch LowVig odds for one sport (BookMaker-group brand)."""
    return await _fetch_book(sport, "lowvig", limit)


async def fetch_youwager(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch YouWager odds for one sport (legacy book; best-effort)."""
    return await _fetch_book(sport, "youwager", limit)


async def fetch_everygame(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Everygame odds for one sport (legacy book; best-effort)."""
    return await _fetch_book(sport, "everygame", limit)


async def fetch_gtbets(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch GTbets odds for one sport (legacy book; best-effort)."""
    return await _fetch_book(sport, "gtbets", limit)


# ── Aggregate ───────────────────────────────────────────────────────────


async def fetch_offshore_odds(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Aggregate odds for one sport across every offshore book.

    Runs all per-book fetchers concurrently and reuses the existing
    Bovada + BetOnline fetchers from :mod:`sports_data.sources` (same
    offshore tier — extended, never duplicated). One dead or geo-blocked
    book never affects the others.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``
            or ``"nba"``).
        limit: Max events to parse per book (each book may yield several
            records per event; matches the per-source cap convention in
            ``sports_data.sources``).

    Returns:
        Canonical odds records from every reachable book; ``[]`` on any
        failure. Never raises.
    """
    try:
        fetchers: list[Any] = [_fetch_book(sport, book, limit) for book in OFFSHORE_BOOK_ORDER]
        # Reuse the existing offshore fetchers rather than duplicating them.
        fetchers.append(sources.fetch_bovada(sport))
        fetchers.append(sources.fetch_betonline(sport))
        results = await asyncio.gather(*fetchers, return_exceptions=True)
    except (httpx.HTTPError, OSError, ValueError):
        return []
    records: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        if not isinstance(result, list):
            continue
        records.extend(record for record in result if isinstance(record, dict))
    return records
