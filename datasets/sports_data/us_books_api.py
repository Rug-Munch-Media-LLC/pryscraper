"""Public fetchers + orchestrator for the US geo-fenced sportsbooks.

Extracted from :mod:`datasets.sports_data.us_books` — the per-book
``fetch_*`` wrappers and the :func:`fetch_us_odds` aggregate. The per-book
fetch core (transport, health tracking, URL building) stays in
:mod:`datasets.sports_data.us_books` so test patches of
``us_books._fetch_json_via_proxy`` / ``us_books.next_webshare_proxy``
keep working.

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

from datasets.sports_data.us_books import (
    _US_BOOK_IDS,
    _canonical_sport,
    _clamp_limit,
    _fetch_book,
    _resolve_sports,
)

logger = logging.getLogger(__name__)


async def _fetch_book_for(book_id: str, sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Resolve a sport alias and delegate to the shared per-book core."""
    if _resolve_sports is None:
        return []
    slugs = _resolve_sports(sport)
    if not slugs:
        return []
    return await _fetch_book(book_id, _canonical_sport(slugs[0]), limit)


async def fetch_draftkings(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch DraftKings odds for one sport (US proxy required)."""
    return await _fetch_book_for("draftkings", sport, limit)


async def fetch_fanduel(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch FanDuel odds for one sport (US proxy + warm session often required)."""
    return await _fetch_book_for("fanduel", sport, limit)


async def fetch_betmgm(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BetMGM odds for one sport (needs x-bwin-accessid; browser tier)."""
    return await _fetch_book_for("betmgm", sport, limit)


async def fetch_caesars(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Caesars odds for one sport (browser tier usually required)."""
    return await _fetch_book_for("caesars", sport, limit)


async def fetch_pointsbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch PointsBet odds for one sport (public JSON feed)."""
    return await _fetch_book_for("pointsbet", sport, limit)


async def fetch_betrivers(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BetRivers odds for one sport (US geo required)."""
    return await _fetch_book_for("betrivers", sport, limit)


async def fetch_barstool(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Barstool odds for one sport (legacy; mostly folded into ESPN BET)."""
    return await _fetch_book_for("barstool", sport, limit)


async def fetch_wynnbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch WynnBET odds for one sport (platform shut down 2024)."""
    return await _fetch_book_for("wynnbet", sport, limit)


async def fetch_betway_us(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Betway US odds for one sport (limited US footprint)."""
    return await _fetch_book_for("betway_us", sport, limit)


async def fetch_hardrock(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Hard Rock odds for one sport (Kambi frontend, undocumented)."""
    return await _fetch_book_for("hardrock", sport, limit)


async def fetch_espnbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch ESPN BET odds for one sport (Penn internal API, browser tier)."""
    return await _fetch_book_for("espnbet", sport, limit)


async def fetch_us_odds(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch US sportsbook odds across every book in ``US_BOOKS``.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``
            or ``"nba"``); ``""`` / ``"all"`` resolves to the default sports
            (same as ``sports_data.odds.get_odds``).
        limit: Max records to return (default 50). Each book is fetched with
            this cap and the merged result is truncated to it.

    Returns:
        Canonical odds records from every book that responded, tagged
        ``source="us_<book_id>"``; ``[]`` when no book yielded odds (every
        book geo-blocked / failed) or the sport is unsupported. Never
        raises — each book is fetched independently via ``asyncio.gather``
        with ``return_exceptions=True`` so one failure never affects the
        others.
    """
    if _resolve_sports is None:
        return []
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_us_books_unsupported_sport", extra={"sport": sport})
        return []
    clamped = _clamp_limit(limit)
    records: list[dict[str, Any]] = []
    for slug in slugs:
        jobs = [_dispatch_book(book_id, slug) for book_id in _US_BOOK_IDS]
        results = await asyncio.gather(*jobs, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                continue
            for record in result:
                if isinstance(record, dict):
                    records.append(record)
    records.sort(key=lambda record: str(record.get("last_update") or ""), reverse=True)
    return records[:clamped]


async def _dispatch_book(book_id: str, slug: str) -> list[dict[str, Any]]:
    """Fetch one book for one raw sport slug (gather-safe wrapper)."""
    try:
        return await _fetch_book(book_id, _canonical_sport(slug))
    except (httpx.HTTPError, OSError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "us_book_fetch_failed",
            extra={"book": book_id, "sport": slug, "error": str(exc)[:120]},
        )
        return []
