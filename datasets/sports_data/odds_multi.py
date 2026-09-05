"""Multi-source event odds aggregation for the sports odds engine.

:func:`get_odds_multi` resolves one event through the core comparison
path, then fetches from every reachable source in parallel and returns
the merged, deduped record set. Patchable odds-engine callables are
resolved through a late ``odds`` module handle so test monkeypatches on
``sports_data.odds`` keep taking effect.

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

from datasets.sports_data.odds_common import (
    _MAX_LIMIT,
    _SPORTS,
    _as_text,
    _normalize_markets,
    _parse_sources_param,
)

logger = logging.getLogger(__name__)


async def get_odds_multi(
    event_id: str,
    market: str = "h2h",
    book: str | None = None,
    limit: int = 50,
    sources: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate one event's odds from every reachable source.

    Resolves the event (label + sport) through the core comparison path,
    then fetches from each reachable source in parallel via
    ``asyncio.gather`` (The Odds API / ESPN core plus OddsPortal, Bovada
    and BetOnline where the sport is mapped, and the 112-book direct
    scrapers when ``sources`` includes ``"books"`` or ``"all"``) and
    returns the merged, deduped record set
    (:func:`sports_data.sources.merge_odds` — Pinnacle wins conflicts).
    Each source degrades independently.

    Args:
        event_id: The event id; accepts an optional ``sport:event_id``
            prefix (e.g. ``nba:bda33adc...``) like :func:`get_event_odds`.
        market: Market(s) to include (default ``"h2h"``).
        book: Optional single-book filter (e.g. ``"draftkings"``).
        limit: Max records to return (1-100).
        sources: Optional comma-separated source list (see
            :func:`sports_data.odds.get_odds`); ``None`` queries every
            reachable source except the 112-book scrapers (those require
            an explicit ``"books"`` / ``"all"``).

    Returns:
        A deduped list of canonical odds records for the event. ``[]`` when
        the event cannot be resolved or nothing is reachable. Never raises.
    """
    try:
        return await _get_odds_multi(event_id, market, book, limit, sources)
    except Exception:
        logger.exception(
            "sports_odds_multi_crashed",
            extra={"event_id": event_id, "market": market, "book": book},
        )
        return []


async def _get_odds_multi(
    event_id: str,
    market: str,
    book: str | None,
    limit: int,
    sources: str | None,
) -> list[dict[str, Any]]:
    # Late handle: the odds engine owns the patchable callables
    # (_get_event_odds, _get_odds, _espn_odds_for_league,
    # _books_odds_for_sport) and is imported lazily to avoid the package
    # __init__ cycle.
    from datasets.sports_data import odds as _odds, sources as _odds_sources

    if not event_id or not str(event_id).strip():
        return []
    # Resolve event meta (label + sport) through the existing comparison
    # path — never raises.
    comparison = await _odds._get_event_odds(event_id, market, book)
    label = _as_text(comparison.get("event")) if comparison else None
    sport = _as_text(comparison.get("sport")) if comparison else None
    if not label:
        return []
    slug = sport if sport and sport in _SPORTS else ""
    if not slug:
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    markets = _normalize_markets(market)
    book_key = _odds._canonical_book(book) if book else None
    key = _odds._api_key()
    wanted = _parse_sources_param(sources)

    jobs: list[tuple[str, Any]] = []
    if key and (wanted is None or "the_odds_api" in wanted):
        jobs.append(
            (
                "the_odds_api",
                _odds._get_odds(
                    event_query=label, sport=slug, limit=_MAX_LIMIT, market=market, book=book
                ),
            )
        )
    if wanted is None or "espn" in wanted:
        espn = _SPORTS[slug][1]
        jobs.append(("espn", _odds._espn_odds_for_league(espn, slug, markets)))
    for name in ("oddsportal", "bovada", "betonline"):
        if wanted is not None and name not in wanted:
            continue
        if not _odds_sources.source_supports(name, slug):
            continue
        if name == "oddsportal":
            jobs.append((name, _odds_sources.fetch_oddsportal(slug, limit=8)))
        elif name == "bovada":
            jobs.append((name, _odds_sources.fetch_bovada(slug)))
        else:
            jobs.append((name, _odds_sources.fetch_betonline(slug)))
    # The 112-book direct scrapers are only pulled when explicitly
    # requested ("books" / "all") — they are the heaviest source and the
    # default ``sources=None`` behavior stays unchanged.
    if wanted is not None and "books" in wanted:
        jobs.append(("books", _odds._books_odds_for_sport(slug, markets, book_key, limit=clamped)))

    if not jobs:
        return []
    results = await asyncio.gather(*(job for _name, job in jobs), return_exceptions=True)
    records: list[dict[str, Any]] = []
    for (name, _job), result in zip(jobs, results, strict=False):
        if isinstance(result, BaseException):
            logger.warning(
                "sports_odds_multi_source_failed",
                extra={"event_id": event_id, "source": name},
            )
            continue
        for record in result or []:
            if not isinstance(record, dict):
                continue
            if record.get("market") not in markets:
                continue
            if not (
                _odds_sources.event_matches(record, label)
                or _odds_sources._event_id_matches(record, comparison.get("event_id"))
            ):
                continue
            if book_key is not None and record.get("book") != book_key:
                continue
            records.append(record)
    if len({record.get("source") for record in records}) > 1:
        records = _odds_sources.merge_odds(records)
    records.sort(key=lambda record: str(record.get("last_update") or ""), reverse=True)
    return records[:clamped]
