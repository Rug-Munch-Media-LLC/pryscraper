"""Source fetchers (The Odds API + ESPN) and public API for alternate lines.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from datasets.sports_data.alt_lines_common import (
    _ESPN_SCOREBOARD,
    _ODDS_API_REGIONS,
    _ODDS_BASE,
    _SPORTS,
    _api_key,
    _as_text,
    _book_api_param,
    _canonical_book,
    _event_label,
    _fetch_json,
    _normalize_markets,
    _resolve_event,
    logger,
)
from datasets.sports_data.alt_lines_parsers import (
    _espn_base_line,
    _espn_competitors,
    _map_alt_event,
    _modeled_spread_lines,
    _modeled_total_lines,
)


async def _alt_lines_odds_api(
    event_id: str, sport_slug: str, wanted: set[str], book_slug: str | None
) -> list[dict[str, Any]]:
    """Fetch real alternate markets from The Odds API for one event."""
    key = _api_key()
    if not key:
        return []
    odds_key, _espn = _SPORTS[sport_slug]
    url = f"{_ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds"
    alt_market_keys = {"alternate_spreads": "spread", "alternate_totals": "total"}
    markets = [key for key, cls in alt_market_keys.items() if cls in wanted]
    if not markets:
        return []
    params: dict[str, str] = {
        "apiKey": key,
        "regions": _ODDS_API_REGIONS,
        "markets": ",".join(markets),
        "oddsFormat": "decimal",
    }
    api_book = _book_api_param(book_slug or "all")
    if api_book:
        params["bookmakers"] = api_book
    payload = await _fetch_json(url, params)
    if not isinstance(payload, dict):
        return []
    return _map_alt_event(payload, sport_slug, wanted, book_slug)


async def _espn_alt_lines(event_id: str, sport_slug: str, wanted: set[str]) -> list[dict[str, Any]]:
    """Synthesize an alternate-line ladder from ESPN's base lines (no key)."""
    _odds_key, espn = _SPORTS[sport_slug]
    if espn is None:
        return []
    url = _ESPN_SCOREBOARD.format(sport=espn[0], league=espn[1])
    payload = await _fetch_json(url)
    if not isinstance(payload, dict):
        return []
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        competitions = ev.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            continue
        comp = competitions[0]
        if not isinstance(comp, dict):
            continue
        if _as_text(ev.get("id")) != event_id and _as_text(comp.get("id")) != event_id:
            continue
        home, away = _espn_competitors(comp)
        event = _event_label(home, away)
        if not event:
            return []
        spread, total = _espn_base_line(comp)
        records: list[dict[str, Any]] = []
        if "spread" in wanted and spread is not None:
            records.extend(_modeled_spread_lines(event, event_id, sport_slug, spread))
        if "total" in wanted and total is not None:
            records.extend(_modeled_total_lines(event, event_id, sport_slug, total))
        return records
    return []


async def get_alt_lines(
    event_id: str, market: str = "spread|total", book: str = "all"
) -> list[dict[str, Any]]:
    """Fetch alternative spreads/totals for one event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:eid123`` or ``basketball_nba:...``) to skip the
            default-sport scan.
        market: ``"spread"``, ``"total"``, comma/pipe separated combos, or
            ``"spread|total"`` / ``"all"`` (default) for both.
        book: Optional single-book filter (e.g. ``"draftkings"``). Default
            ``"all"``.

    Returns:
        A list of alt-line records (see module docstring). ``[]`` on
        failure, unknown event, or when the source publishes no alternates.
        Never raises.
    """
    try:
        return await _get_alt_lines(event_id, market, book)
    except Exception:  # noqa: BLE001 - intentional catch-all, logged below
        logger.exception(
            "sports_alt_lines_crashed",
            extra={"event_id": event_id, "market": market, "book": book},
        )
        return []


async def _get_alt_lines(event_id: str, market: str, book: str) -> list[dict[str, Any]]:
    if not event_id or not str(event_id).strip():
        return []
    wanted = _normalize_markets(market)
    if not wanted:
        logger.warning("sports_alt_lines_invalid_market", extra={"market": market})
        return []
    slugs, target_id = _resolve_event(event_id)
    if not slugs:
        logger.warning("sports_alt_lines_invalid_sport", extra={"event_id": event_id})
        return []
    book_slug = None
    if _canonical_book is not None and str(book or "").strip().lower() not in {"", "all"}:
        book_slug = _canonical_book(book)
    records: list[dict[str, Any]] = []
    for slug in slugs:
        if _api_key():
            records = await _alt_lines_odds_api(target_id, slug, wanted, book_slug)
            if records:
                break
        else:
            records = await _espn_alt_lines(target_id, slug, wanted)
            if records:
                break
    return records


__all__ = ["get_alt_lines"]
