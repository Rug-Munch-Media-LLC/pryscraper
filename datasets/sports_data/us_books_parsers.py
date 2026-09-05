"""Book-specific payload parsers for the US geo-fenced sportsbooks.

Extracted from :mod:`datasets.sports_data.us_books` — one parser per known
upstream JSON shape (DraftKings eventgroups, FanDuel eventGroup + cache
variant, PointsBet featured events) plus a best-effort generic parser for
the undocumented books. Pure functions: no transport, no I/O.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from datasets.sports_data.us_books_normalize import (
    _MARKET_H2H,
    _MARKET_SPREADS,
    _MARKET_TOTALS,
    _as_text,
    _event_label,
    _market_blocks,
    _market_key,
    _market_records,
    _selections_of,
    _split_event_name,
)


def _event_identity(event: dict[str, Any], name: str | None) -> tuple[str | None, str | None]:
    """Derive (home, away) from explicit event fields or the event name."""
    home = _as_text(event.get("home")) or _as_text(event.get("homeTeam"))
    away = _as_text(event.get("away")) or _as_text(event.get("awayTeam"))
    if not home or not away:
        parsed_away, parsed_home = _split_event_name(name)
        home = home or parsed_home
        away = away or parsed_away
    return home, away


def _parse_dk_eventgroup(
    payload: Any,
    sport: str,
    book: str,
    bookmaker: str,
) -> list[dict[str, Any]]:
    """Parse a DraftKings eventgroups JSON payload into canonical records.

    Expected shape: ``{"groupedMarkets": [{"event": {...}, "moneyline":
    {...}, "spread": {...}, "total": {...}}, ...]}`` with an alternate
    ``main`` array of ``{"marketType": "MONEYLINE"|"SPREAD"|"TOTAL",
    "outcomes": [...]}`` blocks.
    """
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    grouped = payload.get("groupedMarkets")
    if not isinstance(grouped, list):
        return records
    last_update = _payload_timestamp(payload)
    for group in grouped:
        if not isinstance(group, dict):
            continue
        raw_event = group.get("event")
        event = raw_event if isinstance(raw_event, dict) else {}
        event_id = _as_text(event.get("id"))
        name = _as_text(event.get("name"))
        home, away = _event_identity(event, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        blocks = _dk_blocks(group)
        for block in blocks:
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=event_id,
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _dk_blocks(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect canonical market blocks from one DraftKings group."""
    blocks: list[dict[str, Any]] = []
    for raw_key, market in (
        ("moneyline", _MARKET_H2H),
        ("spread", _MARKET_SPREADS),
        ("total", _MARKET_TOTALS),
    ):
        block = group.get(raw_key)
        selections = _selections_of(block)
        if selections:
            blocks.append({"market": market, "selections": selections})
    if blocks:
        return blocks
    main = group.get("main")
    if isinstance(main, list):
        for item in main:
            if not isinstance(item, dict):
                continue
            key = _market_key(item.get("marketType"))
            if key is None:
                continue
            selections = _selections_of(item)
            if selections:
                blocks.append({"market": key, "selections": selections})
    return blocks


def _parse_fanduel_eventgroup(
    payload: Any,
    sport: str,
    book: str,
    bookmaker: str,
) -> list[dict[str, Any]]:
    """Parse a FanDuel eventGroup JSON payload into canonical records.

    Expected shape: ``{"eventGroup": {...}, "events": [{"event": {...},
    "markets": [{"name": "Moneyline", "selections": [{"name": ..., "odds":
    {"american": ..., "decimal": ...}, "handicap": ...}]}]}]}``. Also handles
    the cache/psevent variant (``eventmarketgroups`` -> ``markets``).
    """
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    last_update = _payload_timestamp(payload)
    events = payload.get("events")
    if not isinstance(events, list):
        return _parse_fanduel_cache(payload, sport, book, bookmaker, last_update)
    for item in events:
        if not isinstance(item, dict):
            continue
        raw_event = item.get("event")
        event = raw_event if isinstance(raw_event, dict) else item
        event_id = _as_text(event.get("id"))
        name = _as_text(event.get("name"))
        home, away = _event_identity(event, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        markets = item.get("markets")
        if markets is None:
            markets = event.get("markets")
        for block in _market_blocks(markets):
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=event_id,
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _parse_fanduel_cache(
    payload: dict[str, Any],
    sport: str,
    book: str,
    bookmaker: str,
    last_update: str | None,
) -> list[dict[str, Any]]:
    """Parse the FanDuel cache/psevent variant (eventmarketgroups)."""
    records: list[dict[str, Any]] = []
    groups = payload.get("eventmarketgroups")
    if not isinstance(groups, list):
        return records
    for group in groups:
        if not isinstance(group, dict):
            continue
        raw_event = group.get("event")
        event = raw_event if isinstance(raw_event, dict) else {}
        name = _as_text(event.get("name") or group.get("eventName"))
        home, away = _event_identity(event, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        for block in _market_blocks(group.get("markets")):
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=_as_text(event.get("id") or group.get("eventId")),
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _parse_pointsbet_events(
    payload: Any,
    sport: str,
    book: str,
    bookmaker: str,
) -> list[dict[str, Any]]:
    """Parse a PointsBet featured-events JSON payload into canonical records.

    Expected shape: ``{"events": [{"id"/"key", "name", "markets": [{"name":
    "Moneyline"|"Point Spread"|"Total Points", "selections": [{"name",
    "price" (decimal), "point"}]}]}]}``.
    """
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    events = payload.get("events")
    if not isinstance(events, list):
        return records
    last_update = _payload_timestamp(payload)
    for item in events:
        if not isinstance(item, dict):
            continue
        event_id = _as_text(item.get("id") or item.get("key"))
        name = _as_text(item.get("name"))
        home, away = _event_identity(item, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        markets = item.get("markets")
        if markets is None:
            markets = item.get("featuredMarkets")
        for block in _market_blocks(markets):
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=event_id,
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _parse_generic_events(
    payload: Any,
    sport: str,
    book: str,
    bookmaker: str,
) -> list[dict[str, Any]]:
    """Best-effort parser for books whose JSON shape is not well documented.

    Handles ``events`` / ``fixtures`` / ``eventGroups`` containers with
    either wrapped (``{"event": {...}}``) or flat event dicts carrying a
    ``markets`` array (FanDuel-like). Used by BetMGM, Caesars, Barstool,
    WynnBET, Betway US, Hard Rock and ESPN BET — those feeds are
    undocumented and session-bound, so this is honest best-effort: it only
    yields records when the payload happens to match a known shape.
    """
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    last_update = _payload_timestamp(payload)
    container: Any = None
    for key in ("events", "fixtures", "eventGroups", "offerGrouping"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            container = candidate
            break
    if container is None:
        return records
    for item in container:
        if not isinstance(item, dict):
            continue
        raw_event = item.get("event")
        event = raw_event if isinstance(raw_event, dict) else item
        event_id = _as_text(event.get("id") or event.get("eventId"))
        name = _as_text(event.get("name"))
        home, away = _event_identity(event, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        markets = item.get("markets")
        if markets is None:
            markets = event.get("markets")
        for block in _market_blocks(markets):
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=event_id,
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _payload_timestamp(payload: Any) -> str:
    """Best-effort freshness timestamp from a payload, else now (UTC)."""
    if isinstance(payload, dict):
        for key in ("lastUpdate", "lastModified", "generatedAt", "timestamp"):
            value = _as_text(payload.get(key))
            if value:
                return value
    return datetime.now(UTC).isoformat()
