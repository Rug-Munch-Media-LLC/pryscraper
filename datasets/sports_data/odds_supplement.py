"""Supplementary odds sources (scrape/offshore/112-book registry) glue.

Fetches records from the non-core sources (OddsPortal, Bovada, BetOnline,
the 112-book direct scrapers) for one sport and filters them into the
canonical schema. Each source degrades independently — one failure never
affects the others.

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

logger = logging.getLogger(__name__)


async def _supplementary_records(
    wanted: set[str],
    slug: str,
    markets: list[str],
    book_key: str | None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch records from the scrape/offshore sources for one sport.

    Each source is fetched independently (``asyncio.gather`` with
    ``return_exceptions=True``) so one failure never affects the others.
    ``books`` (the 112-book direct scrapers) participates too when
    requested; it is imported lazily because that module can land from a
    parallel edit.
    """
    from datasets.sports_data import sources as _odds_sources

    jobs: list[tuple[str, Any]] = []
    if "oddsportal" in wanted and _odds_sources.source_supports("oddsportal", slug):
        jobs.append(("oddsportal", _odds_sources.fetch_oddsportal(slug)))
    if "bovada" in wanted and _odds_sources.source_supports("bovada", slug):
        jobs.append(("bovada", _odds_sources.fetch_bovada(slug)))
    if "betonline" in wanted and _odds_sources.source_supports("betonline", slug):
        jobs.append(("betonline", _odds_sources.fetch_betonline(slug)))
    if "books" in wanted:
        jobs.append(("books", _books_odds_for_sport(slug, markets, book_key, limit=limit)))
    if not jobs:
        return []
    results = await asyncio.gather(*(job for _name, job in jobs), return_exceptions=True)
    records: list[dict[str, Any]] = []
    for (name, _job), result in zip(jobs, results, strict=False):
        if isinstance(result, BaseException):
            logger.warning(
                "sports_supplementary_source_failed", extra={"source": name, "sport": slug}
            )
            continue
        for record in result or []:
            if not isinstance(record, dict):
                continue
            if record.get("market") not in markets:
                continue
            if book_key is not None and record.get("book") != book_key:
                continue
            records.append(record)
    return records


async def _books_odds_for_sport(
    slug: str,
    markets: list[str],
    book_key: str | None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Pull normalized odds from the 112-book scraper registry for one sport.

    The ``sports_data.books`` module may be edited in parallel, so the
    import is guarded: if it is momentarily unavailable the books source
    simply contributes nothing (never raises). Records are copied and
    tagged ``source="books"`` (the pipeline-level source name); the
    per-book identity stays in ``book`` / ``book_id``.
    """
    try:
        from datasets.sports_data import books as _books
    except Exception:  # noqa: BLE001 - guarded parallel import
        logger.warning("sports_books_module_unavailable", extra={"sport": slug})
        return []
    try:
        market_arg = markets[0] if len(markets) == 1 else "all"
        records = await _books.get_all_books_odds(sport=slug, market=market_arg, limit=limit)
    except Exception:  # noqa: BLE001 - never raise
        logger.warning("sports_books_failed", extra={"sport": slug})
        return []
    tagged: list[dict[str, Any]] = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if record.get("market") not in markets:
            continue
        if book_key is not None and record.get("book_id") != book_key:
            continue
        copy = dict(record)
        copy["source"] = "books"
        copy["sport"] = slug
        tagged.append(copy)
    return tagged
