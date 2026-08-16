"""Player props — The Odds API player-props markets + ESPN season-average fallback.

Two sources are aggregated here:

* **The Odds API** (``api.the-odds-api.com``) — real bookmaker player props
  (points, rebounds, assists, passing/rushing/receiving yards, anytime-TD,
  hits, saves, ...) via the v4 ``/sports/{key}/events/{id}/odds`` endpoint
  with ``markets=player_*``. Requires a free API key
  (https://the-odds-api.com) via the ``PRY_ODDS_API_KEY`` env var. The free
  tier is 500 requests/month and each requested market/region/sport counts
  against it, so per-sport market sets are kept small (see
  ``_PROP_MARKETS``) and at most ``_MAX_EVENTS`` events are scanned per
  sport until the target player is found.
* **ESPN public endpoints** (``site.web.api.espn.com``) — no key, no quota.
  When no key is configured (or the Odds API path yields nothing) the module
  synthesizes a *projected line* from the player's current-season per-game
  averages (e.g. points/rebounds/assists per game from ESPN's stats feed).
  Estimates carry no odds (``over_odds``/``under_odds`` are ``None``) and
  are labelled ``book="ESPN Estimate"``, ``source="espn_estimate"`` so
  callers can always tell real bookmaker lines from projections.

Contract
--------
* :func:`get_player_props` — async, never raises, returns a ``list``
  (``[]`` on failure). One record per (player, market, bookmaker).
* :func:`get_game_props` — async, never raises, returns a ``list``. Flattens
  *all* player props for one event; requires an Odds API key (ESPN publishes
  no game-level props feed), ``[]`` without one.

Result shapes
-------------
``get_player_props`` returns a list of:

    {
        "player": "LeBron James",
        "sport": "nba",
        "market": "player_points",
        "line": 25.5,
        "over_odds": 1.91,
        "under_odds": 1.95,
        "book": "DraftKings",
        "source": "the_odds_api",
    }

The ESPN fallback emits the same keys with ``over_odds``/``under_odds`` =
``None`` and ``book="ESPN Estimate"``.

Market names accepted by ``market``: ``points``, ``rebounds``, ``assists``,
``threes``, ``pass_yds``, ``rush_yds``, ``recv_yds``, ``anytime_td``,
``home_runs``, ``hits``, ``rbis``, ``total_bases``, ``shots_on_goal``,
``shots_on_target``, ``tackles``, ``saves`` (or the raw Odds API key, e.g.
``player_points``). ``"all"`` (default) uses the per-sport default set in
``_PROP_MARKETS``.

Sport names match :mod:`sports_data.odds`. Backoff: 1 retry, exponential
(0.1s -> 0.4s). Free-API terms: https://the-odds-api.com.

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
import os
from typing import Any
from urllib.parse import quote

import httpx

from retry import RetryConfig, async_retry
from sports_data.odds import _SPORT_ALIASES, _SPORTS, _resolve_sports

logger = logging.getLogger(__name__)

# The Odds API endpoints. Player props live on the per-event odds endpoint —
# the events list is only used to discover event ids to scan.
_ODDS_BASE = "https://api.the-odds-api.com/v4/sports"
# ESPN endpoints used by the season-average fallback.
_ESPN_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
_ESPN_STATS = (
    "https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/stats"
)

_API_KEY_ENV = "PRY_ODDS_API_KEY"
_TIMEOUT = httpx.Timeout(10.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

_MAX_LIMIT = 100
_MAX_EVENTS = 3
_ODDS_API_REGIONS = "us"
_SEARCH_LIMIT = 5

# User-facing market name -> The Odds API player-props market key.
_MARKET_ALIASES: dict[str, str] = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "threes": "player_3pt_made",
    "3pt": "player_3pt_made",
    "3pm": "player_3pt_made",
    "blocks": "player_blocks",
    "steals": "player_steals",
    "turnovers": "player_turnovers",
    "pass_yds": "player_pass_yds",
    "passing_yards": "player_pass_yds",
    "pass_tds": "player_pass_tds",
    "passing_tds": "player_pass_tds",
    "rush_yds": "player_rush_yds",
    "rushing_yards": "player_rush_yds",
    "rush_attempts": "player_rush_attempts",
    "recv_yds": "player_recv_yds",
    "receiving_yards": "player_recv_yds",
    "receptions": "player_receptions",
    "anytime_td": "player_anytime_td",
    "anytime_touchdown": "player_anytime_td",
    "first_td": "player_first_td",
    "home_runs": "player_home_runs",
    "hits": "player_hits",
    "rbis": "player_rbis",
    "total_bases": "player_total_bases",
    "strikeouts": "player_strikeouts",
    "shots_on_goal": "player_shots_on_goal",
    "shots_on_target": "player_shots_on_target",
    "tackles": "player_tackles",
    "saves": "player_saves",
    "anytime_goal": "player_anytime_goal",
}

# Default market set queried when ``market="all"``. Kept small: each market
# in a call counts against the Odds API free-tier quota.
_PROP_MARKETS: dict[str, list[str]] = {
    "nba": ["player_points", "player_rebounds", "player_assists", "player_3pt_made"],
    "nfl": ["player_pass_yds", "player_rush_yds", "player_recv_yds", "player_anytime_td"],
    "mlb": ["player_home_runs", "player_hits", "player_rbis", "player_total_bases"],
    "nhl": ["player_points", "player_shots_on_goal", "player_assists", "player_saves"],
    "epl": ["player_anytime_goal", "player_shots_on_target", "player_assists", "player_tackles"],
    "ncaab": ["player_points", "player_rebounds", "player_assists"],
    "ncaaf": ["player_pass_yds", "player_rush_yds", "player_recv_yds", "player_anytime_td"],
    "wnba": ["player_points", "player_rebounds", "player_assists"],
    "cfl": ["player_pass_yds", "player_rush_yds", "player_recv_yds"],
    "ufc": [],
}

# ESPN stat-label fragment -> prop market, per sport, for the estimate
# fallback. Only per-game averages translate cleanly to a line.
_ESTIMATE_RULES: dict[str, list[tuple[str, str]]] = {
    "nba": [
        ("Points Per Game", "player_points"),
        ("Rebounds Per Game", "player_rebounds"),
        ("Assists Per Game", "player_assists"),
    ],
    "nfl": [
        ("Passing Yards Per Game", "player_pass_yds"),
        ("Rushing Yards Per Game", "player_rush_yds"),
        ("Receiving Yards Per Game", "player_recv_yds"),
    ],
    "mlb": [("Home Runs", "player_home_runs"), ("RBIs", "player_rbis")],
    "nhl": [
        ("Points Per Game", "player_points"),
        ("Assists Per Game", "player_assists"),
        ("Shots On Goal Per Game", "player_shots_on_goal"),
    ],
    "ncaab": [
        ("Points Per Game", "player_points"),
        ("Rebounds Per Game", "player_rebounds"),
    ],
    "ncaaf": [
        ("Passing Yards Per Game", "player_pass_yds"),
        ("Rushing Yards Per Game", "player_rush_yds"),
        ("Receiving Yards Per Game", "player_recv_yds"),
    ],
    "wnba": [
        ("Points Per Game", "player_points"),
        ("Rebounds Per Game", "player_rebounds"),
    ],
}


def _api_key() -> str:
    """Return the configured The Odds API key (or '' when unset)."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _short_slug(slug: str) -> str:
    """Map a resolved slug (alias or canonical Odds API key) to a config key.

    ``_resolve_sports`` returns whatever the caller passed — both ``"nba"``
    and ``"basketball_nba"`` resolve. Per-sport tables here are keyed by the
    short alias, so canonical keys are folded back onto their alias.
    """
    if slug in _PROP_MARKETS or slug in _ESTIMATE_RULES:
        return slug
    odds_key = _SPORTS[slug][0]
    for alias, canonical in _SPORT_ALIASES.items():
        if canonical == odds_key:
            return alias
    return slug


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    """Coerce a JSON value to float/None ('' / garbage -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_half(value: float) -> float:
    """Round to the nearest 0.5 (the standard player-prop line step)."""
    return round(value * 2) / 2


# ── Fetching ───────────────────────────────────────────────────────────
async def _fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and return the parsed JSON (object or array), or ``None`` on failure."""

    async def _one() -> dict[str, Any] | list[Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("sports props payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Market resolution ───────────────────────────────────────────────────
def _market_keys_for(sport: str, market: str) -> list[str]:
    """Return the list of Odds API market keys for a ``market`` request."""
    raw = str(market or "all").strip().lower()
    if raw in {"", "all"}:
        return list(_PROP_MARKETS.get(_short_slug(sport), []))
    key = _MARKET_ALIASES.get(raw, raw)
    if not key.startswith("player_"):
        return []
    return [key]


# ── The Odds API mapping ───────────────────────────────────────────────
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
    over: float | None = None
    under: float | None = None
    for outcome in matched:
        name = str(outcome.get("name") or "").strip().lower()
        price = _to_float(outcome.get("price"))
        if price is None:
            continue
        if name.startswith("over") and over is None:
            over = price
        elif name.startswith("under") and under is None:
            under = price
    if over is None and under is None and len(matched) >= 2:
        over = _to_float(matched[0].get("price"))
        under = _to_float(matched[1].get("price"))
    if over is None and under is None and matched:
        over = _to_float(matched[0].get("price"))
    return over, under, point


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


async def _props_for_player_odds_api(
    slug: str, player_q: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Scan up to ``_MAX_EVENTS`` upcoming events for one player's real lines."""
    odds_key, _espn = _SPORTS[slug]
    key = _api_key()
    events_url = f"{_ODDS_BASE}/{quote(odds_key)}/events"
    events = await _fetch_json(events_url, {"apiKey": key})
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
        if scanned > _MAX_EVENTS:
            break
        url = f"{_ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds"
        params = {
            "apiKey": key,
            "regions": _ODDS_API_REGIONS,
            "markets": ",".join(market_keys),
            "oddsFormat": "decimal",
        }
        payload = await _fetch_json(url, params)
        if isinstance(payload, dict):
            records.extend(_map_props_event(payload, slug, player_q, market_keys))
        if records:
            break  # found real lines — stop scanning more events
    return records


# ── ESPN season-average fallback ───────────────────────────────────────
async def _espn_search_athlete(
    name: str, espn_sport: str, espn_league: str
) -> tuple[str, str | None] | None:
    """Resolve a player name to (athlete_id, team_name), or None."""
    payload = await _fetch_json(
        _ESPN_SEARCH,
        {
            "query": name,
            "type": "player",
            "sport": espn_sport,
            "league": espn_league,
            "limit": str(_SEARCH_LIMIT),
        },
    )
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").lower() not in {"player", "athlete"}:
            continue
        athlete_id = _as_text(item.get("id"))
        if not athlete_id:
            continue
        team = None
        relationships = item.get("teamRelationships")
        if isinstance(relationships, list):
            for rel in relationships:
                if not isinstance(rel, dict):
                    continue
                team_name = _as_text(rel.get("displayName"))
                if team_name:
                    team = team_name
                    break
        return athlete_id, team
    return None


def _extract_stat_map(payload: dict[str, Any]) -> dict[str, str]:
    """Flatten an ESPN stats payload to a label -> displayValue map.

    Handles the ``categories[].statistics[]`` shape (parallel
    ``displayNames``/``stats`` arrays, most recent season last) and the
    simpler ``categories[].stats[]`` shape.
    """
    stats: dict[str, str] = {}
    categories = payload.get("categories")
    if not isinstance(categories, list):
        return stats
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        display_names = cat.get("displayNames")
        if isinstance(display_names, list):
            statistics = cat.get("statistics")
            if isinstance(statistics, list) and statistics:
                latest = statistics[-1]
                if isinstance(latest, dict) and isinstance(latest.get("stats"), list):
                    for label, value in zip(display_names, latest["stats"], strict=False):
                        label_text = _as_text(label)
                        value_text = _as_text(value)
                        if label_text and value_text is not None:
                            stats[label_text] = value_text
        stat_list = cat.get("stats")
        if isinstance(stat_list, list):
            for entry in stat_list:
                if not isinstance(entry, dict):
                    continue
                label = _as_text(entry.get("displayName")) or _as_text(entry.get("name"))
                if not label:
                    continue
                value = entry.get("displayValue")
                if value is None:
                    value = entry.get("value")
                value_text = _as_text(value)
                if value_text is not None:
                    stats[label] = value_text
    return stats


async def _espn_estimate_props(
    player_q: str, slug: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Synthesize projected prop lines from ESPN season averages (no key)."""
    short = _short_slug(slug)
    rules = _ESTIMATE_RULES.get(short)
    if not rules:
        return []
    espn = _SPORTS[slug][1]
    if espn is None:
        return []
    espn_sport, espn_league = espn
    found = await _espn_search_athlete(player_q, espn_sport, espn_league)
    if found is None:
        return []
    athlete_id, _team = found
    url = _ESPN_STATS.format(sport=espn_sport, league=espn_league, id=athlete_id)
    payload = await _fetch_json(url)
    if not isinstance(payload, dict):
        return []
    stats = _extract_stat_map(payload)
    records: list[dict[str, Any]] = []
    for fragment, market_key in rules:
        if market_key not in market_keys:
            continue
        line: float | None = None
        for label, value in stats.items():
            if fragment.casefold() in label.casefold():
                line = _to_float(value)
                break
        if line is None:
            continue
        records.append(
            {
                "player": player_q,
                "sport": short,
                "market": market_key,
                "line": _round_half(line),
                "over_odds": None,
                "under_odds": None,
                "book": "ESPN Estimate",
                "source": "espn_estimate",
            }
        )
    return records


# ── Public API ─────────────────────────────────────────────────────────
async def get_player_props(
    player: str, sport: str = "all", market: str = "all", limit: int = 20
) -> list[dict[str, Any]]:
    """Fetch player props across bookmakers for one or more sports.

    Args:
        player: Player name (e.g. ``"LeBron James"``).
        sport: Sport name (see module docstring) or ``"all"`` (default).
        market: Prop market name (see module docstring) or ``"all"``
            (default, per-sport default set).
        limit: Max records to return (1-100).

    Returns:
        A list of prop records (see module docstring). ``[]`` on failure,
        invalid sport, or unknown player. Never raises.
    """
    try:
        return await _get_player_props(player, sport, market, limit)
    except Exception:
        logger.exception(
            "sports_player_props_crashed",
            extra={"player": player, "sport": sport, "market": market},
        )
        return []


async def _get_player_props(
    player: str, sport: str, market: str, limit: int
) -> list[dict[str, Any]]:
    name = str(player or "").strip()
    if not name:
        return []
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_props_invalid_sport", extra={"sport": sport})
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    key = _api_key()
    records: list[dict[str, Any]] = []
    for slug in slugs:
        market_keys = _market_keys_for(slug, market)
        if not market_keys:
            continue
        if key:
            records.extend(await _props_for_player_odds_api(slug, name, market_keys))
        else:
            records.extend(await _espn_estimate_props(name, slug, market_keys))
    records.sort(key=lambda record: str(record.get("book") or ""))
    return records[:clamped]


async def get_game_props(event_id: str) -> list[dict[str, Any]]:
    """Fetch all player props for a single event.

    Args:
        event_id: The event id. Accepts an optional ``sport:event_id`` prefix
            (e.g. ``nba:eid123`` or ``basketball_nba:...``) to skip the
            default-sport scan.

    Returns:
        A list of prop records for every player with a line in the event.
        ``[]`` on failure or when no Odds API key is configured (ESPN
        publishes no game-level props feed). Never raises.
    """
    try:
        return await _get_game_props(event_id)
    except Exception:
        logger.exception("sports_game_props_crashed", extra={"event_id": event_id})
        return []


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


async def _get_game_props(event_id: str) -> list[dict[str, Any]]:
    if not event_id or not str(event_id).strip():
        return []
    raw_id = str(event_id).strip()
    prefix, _, rest = raw_id.partition(":")
    if rest:
        slugs = _resolve_sports(prefix)
        if not slugs:
            return []
        candidates = slugs
        target_id = rest
    else:
        candidates = list(_resolve_sports("all"))
        target_id = raw_id
    key = _api_key()
    if not key:
        # ESPN publishes no game-level props feed; the per-player fallback
        # lives in get_player_props.
        return []
    for slug in candidates:
        odds_key, _espn = _SPORTS[slug]
        market_keys = _PROP_MARKETS.get(_short_slug(slug), [])
        if not market_keys:
            continue
        url = f"{_ODDS_BASE}/{quote(odds_key)}/events/{quote(target_id)}/odds"
        params = {
            "apiKey": key,
            "regions": _ODDS_API_REGIONS,
            "markets": ",".join(market_keys),
            "oddsFormat": "decimal",
        }
        payload = await _fetch_json(url, params)
        if isinstance(payload, dict) and payload.get("id"):
            return _map_game_props(payload, slug, market_keys)
    return []
