"""The Odds API player-props fetching and payload mapping.

Covers three record shapes, all sourced from the v4
``/sports/{key}/events/{id}/odds`` endpoint with ``markets=player_*``:

* per-player props (:func:`props_for_player`),
* game-level props for every player (:func:`map_game_props`),
* available-market discovery (:func:`map_prop_markets`).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from datasets.sports_data.odds import _SPORTS
from datasets.sports_data.props_http import (
    MAX_EVENTS,
    ODDS_API_REGIONS,
    ODDS_BASE,
    api_key,
    fetch_json,
)
from datasets.sports_data.props_tables import (
    _PROP_MARKETS,
    _market_keys_for,
    _prop_label,
    _short_slug,
)
from datasets.sports_data.props_util import _as_text, _to_float


def _parse_matched(
    outcomes: list[Any], player_q: str
) -> tuple[float | None, float | None, float | None] | None:
    """Extract (over, under, point) for one player from a market's outcomes.

    Handles the two formats The Odds API emits for over/under props:
    outcomes named ``"Over 25.5"`` / ``"Under 25.5"``, or two outcomes with
    identical player names (documented order: Over first, Under second).
    Single-outcome markets (anytime TD, hits, ...) put the "yes" price in
    ``over_odds``.
    """
    matched: list[dict[str, Any]] = []
    needle = player_q.casefold()
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        name = _as_text(outcome.get("name"))
        description = _as_text(outcome.get("description"))
        haystack = " ".join(part for part in (description, name) if part).casefold()
        if needle not in haystack and (name or "").casefold() != needle:
            continue
        matched.append(outcome)
    if not matched:
        return None
    point: float | None = None
    for outcome in matched:
        candidate = _to_float(outcome.get("point"))
        if candidate is not None:
            point = candidate
            break
    over, under = _over_under_from_group(matched)
    return over, under, point


def _over_under_from_group(group: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """Derive (over, under) prices from a player's matched outcomes.

    Prefers explicit ``Over``/``Under`` outcome names; falls back to the
    documented order (Over first, Under second) for two-outcome markets, and
    to the single "yes" price for one-outcome markets.
    """
    over: float | None = None
    under: float | None = None
    for outcome in group:
        name = str(outcome.get("name") or "").strip().lower()
        price = _to_float(outcome.get("price"))
        if price is None:
            continue
        if name.startswith("over") and over is None:
            over = price
        elif name.startswith("under") and under is None:
            under = price
    if over is None and under is None and len(group) >= 2:
        over = _to_float(group[0].get("price"))
        under = _to_float(group[1].get("price"))
    if over is None and under is None and group:
        over = _to_float(group[0].get("price"))
    return over, under


def _map_props_event(
    raw: dict[str, Any], sport_slug: str, player_q: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Map one Odds API event odds payload onto player-prop records."""
    bookmakers = raw.get("bookmakers")
    if not isinstance(bookmakers, list):
        return []
    records: list[dict[str, Any]] = []
    for bk in bookmakers:
        if not isinstance(bk, dict):
            continue
        book = _as_text(bk.get("title")) or _as_text(bk.get("key"))
        if not book:
            continue
        markets = bk.get("markets")
        if not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or ""
            if market_key not in market_keys:
                continue
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            parsed = _parse_matched(outcomes, player_q)
            if parsed is None:
                continue
            over_odds, under_odds, point = parsed
            records.append(
                {
                    "player": player_q,
                    "sport": sport_slug,
                    "market": market_key,
                    "line": point,
                    "over_odds": over_odds,
                    "under_odds": under_odds,
                    "book": book,
                    "source": "the_odds_api",
                }
            )
    return records


async def props_for_player_odds_api(
    slug: str, player_q: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Scan up to ``MAX_EVENTS`` upcoming events for one player's real lines."""
    odds_key, _espn = _SPORTS[slug]
    key = api_key()
    events_url = f"{ODDS_BASE}/{quote(odds_key)}/events"
    events = await fetch_json(events_url, {"apiKey": key})
    if not isinstance(events, list):
        return []
    records: list[dict[str, Any]] = []
    scanned = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_id = _as_text(ev.get("id"))
        if not event_id:
            continue
        scanned += 1
        if scanned > MAX_EVENTS:
            break
        url = f"{ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds"
        params = {
            "apiKey": key,
            "regions": ODDS_API_REGIONS,
            "markets": ",".join(market_keys),
            "oddsFormat": "decimal",
        }
        payload = await fetch_json(url, params)
        if isinstance(payload, dict):
            records.extend(_map_props_event(payload, slug, player_q, market_keys))
        if records:
            break  # found real lines — stop scanning more events
    return records


def _player_of_outcome(outcome: dict[str, Any]) -> str | None:
    """Best-effort player name for a game-level prop outcome.

    The Odds API puts the player name in ``description`` (often with a
    trailing prop phrase like ``"LeBron James Points"``); strip known
    trailing phrases when present.
    """
    description = _as_text(outcome.get("description"))
    if description:
        for marker in (
            " Points",
            " Rebounds",
            " Assists",
            " Threes",
            " Yards",
            " Touchdowns",
            " TD",
            " Hits",
            " Home Runs",
            " RBIs",
            " Total Bases",
            " Strikeouts",
            " Saves",
            " Tackles",
            " Goals",
            " Shots On Target",
            " Shots On Goal",
        ):
            if description.endswith(marker):
                return description[: -len(marker)].strip() or description
        return description
    return _as_text(outcome.get("name"))


def _map_game_props(
    raw: dict[str, Any], sport_slug: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Map one Odds API event odds payload onto records for every player."""
    bookmakers = raw.get("bookmakers")
    if not isinstance(bookmakers, list):
        return []
    records: list[dict[str, Any]] = []
    for bk in bookmakers:
        if not isinstance(bk, dict):
            continue
        book = _as_text(bk.get("title")) or _as_text(bk.get("key"))
        if not book:
            continue
        markets = bk.get("markets")
        if not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or ""
            if market_key not in market_keys:
                continue
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            groups: dict[tuple[str, float | None], list[dict[str, Any]]] = {}
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                player_name = _player_of_outcome(outcome)
                if not player_name:
                    continue
                point = _to_float(outcome.get("point"))
                groups.setdefault((player_name, point), []).append(outcome)
            for (player_name, point), group in groups.items():
                over, under = _over_under_from_group(group)
                records.append(
                    {
                        "player": player_name,
                        "sport": sport_slug,
                        "market": market_key,
                        "line": point,
                        "over_odds": over,
                        "under_odds": under,
                        "book": book,
                        "source": "the_odds_api",
                    }
                )
    return records


def _map_prop_markets(raw: dict[str, Any], sport_slug: str) -> list[dict[str, Any]]:
    """Map one Odds API event odds payload onto available-market records.

    Aggregates the distinct player-prop markets published by any bookmaker
    in the payload, counting distinct players per market.
    """
    event_id = _as_text(raw.get("id"))
    home = _as_text(raw.get("home_team"))
    away = _as_text(raw.get("away_team"))
    event = f"{away} @ {home}" if home and away else None
    bookmakers = raw.get("bookmakers")
    if not isinstance(bookmakers, list):
        return []
    market_info: dict[str, dict[str, Any]] = {}
    for bk in bookmakers:
        if not isinstance(bk, dict):
            continue
        book = _as_text(bk.get("title")) or _as_text(bk.get("key"))
        if not book:
            continue
        markets = bk.get("markets")
        if not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or ""
            if not market_key.startswith("player_"):
                continue
            info = market_info.setdefault(market_key, {"books": set(), "players": set()})
            info["books"].add(book)
            outcomes = mkt.get("outcomes")
            if isinstance(outcomes, list):
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    player = _player_of_outcome(outcome)
                    if player:
                        info["players"].add(player)
    results: list[dict[str, Any]] = []
    for market_key in sorted(market_info):
        info = market_info[market_key]
        results.append(
            {
                "event_id": event_id,
                "event": event,
                "sport": sport_slug,
                "market": market_key,
                "label": _prop_label(market_key),
                "player_count": len(info["players"]),
                "book": sorted(info["books"])[0] if info["books"] else None,
                "books": sorted(info["books"]),
                "source": "the_odds_api",
            }
        )
    return results


def _split_event_id(event_id: str) -> tuple[list[str], str] | None:
    """Split ``sport:event_id`` (or bare id) into (candidate slugs, target id)."""
    from datasets.sports_data.odds import _resolve_sports

    raw_id = str(event_id).strip()
    prefix, _, rest = raw_id.partition(":")
    if rest:
        slugs = _resolve_sports(prefix)
        if not slugs:
            return None
        return slugs, rest
    return list(_resolve_sports("all")), raw_id


async def fetch_event_odds(event_id: str) -> tuple[str, dict[str, Any], list[str]] | None:
    """Fetch one event's odds payload, scanning candidate sports until found.

    Returns ``(sport_slug, payload, market_keys)`` for the first sport whose
    event odds payload resolves, or ``None`` when no key is configured, the
    id is empty, or no candidate sport resolves the event.
    """
    if not event_id or not str(event_id).strip():
        return None
    split = _split_event_id(event_id)
    if split is None:
        return None
    candidates, target_id = split
    key = api_key()
    if not key:
        return None
    for slug in candidates:
        odds_key, _espn = _SPORTS[slug]
        market_keys = _PROP_MARKETS.get(_short_slug(slug), [])
        if not market_keys:
            continue
        url = f"{ODDS_BASE}/{quote(odds_key)}/events/{quote(target_id)}/odds"
        params = {
            "apiKey": key,
            "regions": ODDS_API_REGIONS,
            "markets": ",".join(market_keys),
            "oddsFormat": "decimal",
        }
        payload = await fetch_json(url, params)
        if isinstance(payload, dict) and payload.get("id"):
            return slug, payload, market_keys
    return None


async def game_props_for_event(event_id: str) -> list[dict[str, Any]]:
    """All player props for one event (requires an Odds API key)."""
    found = await fetch_event_odds(event_id)
    if found is None:
        return []
    slug, payload, market_keys = found
    return _map_game_props(payload, slug, market_keys)


async def prop_markets_for_event(event_id: str) -> list[dict[str, Any]]:
    """Available player-prop markets for one event (requires an Odds API key)."""
    found = await fetch_event_odds(event_id)
    if found is None:
        return []
    slug, payload, _market_keys = found
    return _map_prop_markets(payload, slug)


__all__ = [
    "_map_game_props",
    "_map_prop_markets",
    "_map_props_event",
    "_market_keys_for",
    "_parse_matched",
    "_player_of_outcome",
    "_prop_label",
    "fetch_event_odds",
    "game_props_for_event",
    "prop_markets_for_event",
    "props_for_player_odds_api",
]
