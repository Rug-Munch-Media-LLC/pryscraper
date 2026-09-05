"""Player intelligence — lineups, live props, recent stats, streaks, matchups.

The bettor-facing layer on top of the raw odds/props engines. Answers the
questions that decide a player-prop bet *before* the price matters:

* **Who's starting?** — :func:`get_lineups` pulls the ESPN game summary for
  a team's next event and splits the rotation into starters / bench /
  probable pitchers, plus the injury report (questionable / doubtful / out)
  and a per-player minutes projection (season MPG, adjusted down for
  players coming back from injury).
* **What are the lines right now?** — :func:`get_player_props_live` scans
  The Odds API player markets across books for one player and derives a
  cross-book movement signal (``up`` / ``down`` / ``steady``) by comparing
  each book's line against the consensus median.
* **How has he been playing?** — :func:`get_player_recent_stats` pulls the
  ESPN game log for the last N games with per-game stats, averages, and a
  hot/cold trend versus the season average.
* **Is he on a streak?** — :func:`get_player_streaks` condenses the game
  log into a current streak (type, length), average-vs-season deltas, and
  an over/under prop trend.
* **Whole-team board** — :func:`get_team_player_props` aggregates every
  player prop on a team's next event into one list.
* **Matchup context** — :func:`get_props_vs_matchup` returns props for both
  teams in a matchup annotated with how the opponent defends each prop
  type (defensive ranking context from ESPN team stats when available).

Contract
--------
Every public function is async, never raises, and returns its documented
shape (``[]`` / ``{}`` on failure). HTTP goes through :mod:`httpx` with the
shared retry config from :mod:`sports_data.props_http`. Sources:

* **ESPN public APIs** (``site.api.espn.com`` / ``site.web.api.espn.com``)
  — no key, no quota: scoreboard, game summary, rosters, athlete search,
  game logs, team stats.
* **The Odds API** (``api.the-odds-api.com``) — real bookmaker player
  props; requires the ``PRY_ODDS_API_KEY`` env var (free tier). Without a
  key the props functions fall back to ESPN season-average estimates
  (``book="ESPN Estimate"``, no odds) exactly like :mod:`sports_data.props`.

Sport names match :mod:`sports_data.odds` (``nba``, ``nfl``, ``mlb``, ...).

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
import statistics
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
from datasets.sports_data.props_odds_api import (
    _over_under_from_group,
    _player_of_outcome,
)
from datasets.sports_data.props_tables import _PROP_MARKETS, _short_slug
from datasets.sports_data.props_util import _as_text, _to_float

logger = logging.getLogger(__name__)

__all__ = [
    "get_lineups",
    "get_player_props_live",
    "get_player_recent_stats",
    "get_player_streaks",
    "get_props_vs_matchup",
    "get_team_player_props",
]

# ── ESPN endpoints (site.api / site.web.api — no key required) ─────────
ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
ESPN_SCOREBOARD = ESPN_SITE + "/scoreboard"
ESPN_SUMMARY = ESPN_SITE + "/summary"
ESPN_ROSTER = ESPN_SITE + "/teams/{team_id}/roster"
ESPN_TEAM_STATS = ESPN_SITE + "/teams/{team_id}/stats"
ESPN_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search"
ESPN_GAMELOG = (
    "https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/athletes/{id}/gamelog"
)

# Injury statuses that mean "will not play" (minutes projected to 0).
_OUT_STATUSES = {"out", "out for season", "suspended", "injured reserve", "nwt"}
# Statuses that mean "game-time decision" (minutes haircut).
_GAME_TIME = {"questionable", "doubtful", "day-to-day", "game time decision"}

# Minutes haircut applied to players returning from a game-time-decision
# injury (conservative projection until the status clears).
_MINUTES_HAIRCUT = 0.75

# Default prop markets per sport come from data/props.json (prop_markets);
# the matchup defensive context covers the core counting stats.
_DEFENSE_MARKETS: dict[str, tuple[str, ...]] = {
    "nba": ("player_points", "player_rebounds", "player_assists", "player_threes"),
    "wnba": ("player_points", "player_rebounds", "player_assists"),
    "nfl": ("player_pass_yds", "player_rush_yds", "player_recv_yds"),
    "mlb": ("player_hits", "player_home_runs", "player_rbis"),
    "nhl": ("player_points", "player_shots_on_goal"),
}


# ── Small helpers ──────────────────────────────────────────────────────
def _espn_pair(slug: str) -> tuple[str, str] | None:
    """ESPN (sport, league) for a canonical sport slug, or None."""
    entry = _SPORTS.get(slug)
    if not entry or entry[1] is None:
        return None
    return entry[1]


def _name_matches(candidate: str | None, needle: str) -> bool:
    """Case-insensitive substring match on a player/team name."""
    if not candidate:
        return False
    return needle.casefold() in candidate.casefold()


def _median(values: list[float]) -> float | None:
    """Median of a non-empty list, else None."""
    return statistics.median(values) if values else None


def _movement(line: float | None, consensus: float | None) -> str:
    """Cross-book movement signal for one line vs the consensus median."""
    if line is None or consensus is None:
        return "steady"
    if line > consensus:
        return "up"
    if line < consensus:
        return "down"
    return "steady"


# ── Team / event resolution (ESPN scoreboard) ──────────────────────────
def _find_team_event(
    scoreboard: dict[str, Any], needle: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Find (event, competitor) for a team name in an ESPN scoreboard payload."""
    events = scoreboard.get("events")
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict):
            continue
        competitors = _event_competitors(event)
        for competitor in competitors:
            team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}
            if _name_matches(_as_text(team.get("displayName")), needle) or _name_matches(
                _as_text(team.get("name")), needle
            ):
                return event, competitor
    return None


def _find_matchup_event(scoreboard: dict[str, Any], home: str, away: str) -> dict[str, Any] | None:
    """Find the event where ``away`` plays at ``home`` (either order accepted)."""
    events = scoreboard.get("events")
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict):
            continue
        competitors = _event_competitors(event)
        names = []
        for competitor in competitors:
            team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}
            names.append(
                (_as_text(team.get("displayName")) or _as_text(team.get("name")) or "").casefold()
            )
        if _name_matches(" ".join(names), home) and _name_matches(" ".join(names), away):
            return event
    return None


def _event_competitors(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten an ESPN event's competitions[0].competitors."""
    competitions = event.get("competitions")
    if not isinstance(competitions, list) or not competitions:
        return []
    first = competitions[0]
    competitors = first.get("competitors") if isinstance(first, dict) else None
    if not isinstance(competitors, list):
        return []
    return [c for c in competitors if isinstance(c, dict)]


async def _resolve_team(
    team: str, slug: str
) -> tuple[dict[str, Any], dict[str, Any], str, str] | None:
    """Resolve a team name to (event, competitor, espn_sport, espn_league)."""
    espn = _espn_pair(slug)
    if espn is None:
        return None
    espn_sport, espn_league = espn
    scoreboard = await fetch_json(ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league))
    if not isinstance(scoreboard, dict):
        return None
    found = _find_team_event(scoreboard, team)
    if found is None:
        return None
    event, competitor = found
    return event, competitor, espn_sport, espn_league


# ── 1. Lineups ─────────────────────────────────────────────────────────
def _athlete_brief(athlete: Any) -> dict[str, Any]:
    """Compact {id, name, position} from an ESPN athlete object."""
    if not isinstance(athlete, dict):
        return {}
    return {
        "id": _as_text(athlete.get("id")),
        "name": _as_text(athlete.get("displayName")) or _as_text(athlete.get("fullName")),
        "position": _as_text(athlete.get("position", {}).get("abbreviation"))
        if isinstance(athlete.get("position"), dict)
        else None,
    }


def _minutes_from_stats(stat_rows: Any, labels: Any) -> float | None:
    """Extract minutes played from an ESPN boxscore stat row."""
    if not isinstance(stat_rows, list) or not isinstance(labels, list):
        return None
    for row in stat_rows:
        if not isinstance(row, list):
            continue
        for label, value in zip(labels, row, strict=False):
            if str(label).strip().upper() in {"MIN", "MPG", "MINS"}:
                minutes = _to_float(value)
                if minutes is not None:
                    return minutes
    return None


def _parse_summary_lineups(summary: dict[str, Any], competitor: dict[str, Any]) -> dict[str, Any]:
    """Parse an ESPN game summary into the lineup record shape."""
    team_id = _as_text(competitor.get("id"))
    team_name = None
    team_obj = competitor.get("team")
    if isinstance(team_obj, dict):
        team_name = _as_text(team_obj.get("displayName"))

    starters: list[dict[str, Any]] = []
    bench: list[dict[str, Any]] = []
    probable: list[dict[str, Any]] = []
    minutes_projection: dict[str, float] = {}

    boxscore = summary.get("boxscore")
    players = boxscore.get("players") if isinstance(boxscore, dict) else None
    if isinstance(players, list):
        for team_block in players:
            if not isinstance(team_block, dict):
                continue
            block_team = team_block.get("team")
            block_id = _as_text(block_team.get("id")) if isinstance(block_team, dict) else None
            if team_id and block_id and block_id != team_id:
                continue
            entries = team_block.get("entries") or team_block.get("players")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                athlete = entry.get("athlete")
                brief = _athlete_brief(athlete)
                if not brief.get("name"):
                    continue
                stats = entry.get("stats")
                labels = entry.get("labels")
                minutes = _minutes_from_stats(stats, labels)
                if minutes is not None:
                    minutes_projection[str(brief["name"])] = round(minutes, 1)
                starter_flag = entry.get("starter")
                if starter_flag is True or starter_flag == "true":
                    starters.append(brief)
                else:
                    bench.append(brief)

    # Probable pitchers (MLB) / probable starters surface on the summary.
    probables = summary.get("probables")
    if isinstance(probables, list):
        for prob in probables:
            if not isinstance(prob, dict):
                continue
            player = prob.get("player")
            if isinstance(player, dict):
                brief = _athlete_brief(player)
                if brief.get("name"):
                    probable.append(brief)

    # Injury report — split into game-time vs out buckets.
    questionable: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    injuries = summary.get("injuries")
    if isinstance(injuries, list):
        for team_injuries in injuries:
            if not isinstance(team_injuries, dict):
                continue
            inj_team = team_injuries.get("team")
            inj_team_id = _as_text(inj_team.get("id")) if isinstance(inj_team, dict) else None
            if team_id and inj_team_id and inj_team_id != team_id:
                continue
            entries = team_injuries.get("injuries")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                athlete = entry.get("athlete")
                brief = _athlete_brief(athlete)
                if not brief.get("name"):
                    continue
                status = str(entry.get("status") or "").strip().lower()
                brief["status"] = status
                if status in _OUT_STATUSES:
                    out.append(brief)
                    minutes_projection[str(brief["name"])] = 0.0
                elif status in _GAME_TIME:
                    questionable.append(brief)
                    base = minutes_projection.get(str(brief["name"]))
                    if base:
                        minutes_projection[str(brief["name"])] = round(base * _MINUTES_HAIRCUT, 1)

    header = summary.get("header")
    headline = _as_text(header.get("headline")) if isinstance(header, dict) else None

    return {
        "team": team_name,
        "team_id": team_id,
        "sport": None,  # filled by caller
        "event": headline,
        "event_id": _as_text(summary.get("id")),
        "starters": starters,
        "bench": bench,
        "probable": probable,
        "questionable": questionable,
        "out": out,
        "minutes_projection": minutes_projection,
        "source": "espn",
    }


async def get_lineups(team: str, sport: str = "nba") -> dict[str, Any]:
    """Active/projected lineup, injury report, and minutes projection for a team.

    Args:
        team: Team name (e.g. ``"Lakers"``, ``"Boston Celtics"``).
        sport: Sport slug (``nba``, ``nfl``, ``mlb``, ``nhl``, ...).

    Returns:
        A dict::

            {
                "team": "Los Angeles Lakers",
                "team_id": "13",
                "sport": "nba",
                "event": "Lakers vs Celtics",
                "event_id": "401772301",
                "starters": [{"id": "...", "name": "...", "position": "PG"}, ...],
                "bench": [...],
                "probable": [...],        # MLB probable pitchers
                "questionable": [...],    # game-time-decision injuries
                "out": [...],             # ruled out
                "minutes_projection": {"LeBron James": 34.5, ...},
                "source": "espn",
            }

        ``{}`` on failure, unknown team, or no upcoming event. Never raises.
    """
    try:
        return await _get_lineups(team, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_lineups_crashed", extra={"team": team, "sport": sport}
        )
        return {}


async def _get_lineups(team: str, sport: str) -> dict[str, Any]:
    name = str(team or "").strip()
    if not name:
        return {}
    slug = _resolve_one(sport) or ""
    if not slug:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return {}
    resolved = await _resolve_team(name, slug)
    if resolved is None:
        return {}
    event, competitor, espn_sport, espn_league = resolved
    event_id = _as_text(event.get("id"))
    if not event_id:
        return {}
    summary = await fetch_json(
        ESPN_SUMMARY.format(sport=espn_sport, league=espn_league), {"event": event_id}
    )
    if not isinstance(summary, dict):
        return {}
    record = _parse_summary_lineups(summary, competitor)
    record["sport"] = _short_slug(slug)
    return record


def _resolve_one(sport: str) -> str | None:
    """Resolve a sport param to exactly one canonical slug (or None)."""
    raw = str(sport or "").strip().lower()
    if raw in _SPORTS:
        return raw
    return None


# ── 2. Live player props across books ──────────────────────────────────
def _annotate_movement(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add a cross-book ``movement`` signal per (player, market, book) record.

    The consensus line for each (market, line-group) is the median of the
    lines quoted across books; a book quoting above/below the median is
    flagged ``up``/``down`` (its line is richer/shorter than consensus).
    """
    by_market: dict[str, list[float]] = {}
    for record in records:
        line = _to_float(record.get("line"))
        market = str(record.get("market") or "")
        if line is not None:
            by_market.setdefault(market, []).append(line)
    consensus: dict[str, float | None] = {
        market: _median(lines) for market, lines in by_market.items()
    }
    annotated: list[dict[str, Any]] = []
    for record in records:
        line = _to_float(record.get("line"))
        market = str(record.get("market") or "")
        record = dict(record)
        record["prop_type"] = market
        record["movement"] = _movement(line, consensus.get(market))
        annotated.append(record)
    return annotated


async def get_player_props_live(player_name: str, sport: str = "nba") -> list[dict[str, Any]]:
    """All live player props for one player across books, with line movement.

    Args:
        player_name: Player name (e.g. ``"LeBron James"``).
        sport: Sport slug (``nba``, ``nfl``, ...).

    Returns:
        A list of prop records, one per (market, book)::

            {
                "player": "LeBron James",
                "sport": "nba",
                "prop_type": "player_points",
                "market": "player_points",
                "line": 25.5,
                "over_odds": 1.91,
                "under_odds": 1.95,
                "book": "DraftKings",
                "movement": "up",   # up / down / steady vs consensus median
                "source": "the_odds_api",
            }

        With no Odds API key configured, falls back to ESPN season-average
        estimates (``book="ESPN Estimate"``, odds ``None``, ``steady``).
        ``[]`` on failure or unknown player. Never raises.
    """
    try:
        return await _get_player_props_live(player_name, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_props_live_crashed",
            extra={"player": player_name, "sport": sport},
        )
        return []


async def _get_player_props_live(player_name: str, sport: str) -> list[dict[str, Any]]:
    name = str(player_name or "").strip()
    if not name:
        return []
    slug = _resolve_one(sport)
    if not slug:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return []
    market_keys = list(_PROP_MARKETS.get(_short_slug(slug), []))
    if not market_keys:
        return []
    records: list[dict[str, Any]] = []
    key = api_key()
    if key:
        records = await _scan_player_props_odds_api(slug, name, market_keys)
    if not records:
        records = await _espn_estimate_records(name, slug, market_keys)
    return _annotate_movement(records)


async def _scan_player_props_odds_api(
    slug: str, player_q: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Scan upcoming events for one player's lines across all books."""
    odds_key, _espn = _SPORTS[slug]
    key = api_key()
    events = await fetch_json(f"{ODDS_BASE}/{quote(odds_key)}/events", {"apiKey": key})
    if not isinstance(events, list):
        return []
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
        payload = await fetch_json(
            f"{ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds",
            {
                "apiKey": key,
                "regions": ODDS_API_REGIONS,
                "markets": ",".join(market_keys),
                "oddsFormat": "decimal",
            },
        )
        if not isinstance(payload, dict):
            continue
        records = _map_player_props(payload, slug, player_q, market_keys)
        if records:
            return records
    return []


def _map_player_props(
    raw: dict[str, Any], slug: str, player_q: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """Map one Odds API event payload to prop records for one player."""
    needle = player_q.casefold()
    bookmakers = raw.get("bookmakers")
    if not isinstance(bookmakers, list):
        return []
    records: list[dict[str, Any]] = []
    for bk in bookmakers:
        if not isinstance(bk, dict):
            continue
        book = _as_text(bk.get("title")) or _as_text(bk.get("key"))
        markets = bk.get("markets")
        if not book or not isinstance(markets, list):
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
            matched = [
                o
                for o in outcomes
                if isinstance(o, dict)
                and (
                    needle in str(o.get("description") or "").casefold()
                    or needle in str(o.get("name") or "").casefold()
                )
            ]
            if not matched:
                continue
            player_name = _player_of_outcome(matched[0]) or player_q
            point: float | None = None
            for outcome in matched:
                point = _to_float(outcome.get("point"))
                if point is not None:
                    break
            over, under = _over_under_from_group(matched)
            records.append(
                {
                    "player": player_name,
                    "sport": _short_slug(slug),
                    "prop_type": market_key,
                    "market": market_key,
                    "line": point,
                    "over_odds": over,
                    "under_odds": under,
                    "book": book,
                    "source": "the_odds_api",
                }
            )
    return records


async def _espn_estimate_records(
    player_q: str, slug: str, market_keys: list[str]
) -> list[dict[str, Any]]:
    """ESPN season-average projected lines (no Odds API key needed)."""
    from datasets.sports_data.props_espn import espn_estimate_props

    return await espn_estimate_props(player_q, slug, market_keys)


# ── 3. Recent stats (ESPN game log) ────────────────────────────────────
def _parse_gamelog(payload: dict[str, Any], games: int) -> list[dict[str, Any]]:
    """Parse an ESPN gamelog payload into per-game stat dicts (newest last)."""
    labels = payload.get("labels")
    if not isinstance(labels, list):
        return []
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    per_game: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        stats = entry.get("stats")
        if not isinstance(stats, list):
            continue
        game = entry.get("game")
        game_info = game.get("result") if isinstance(game, dict) else None
        record: dict[str, Any] = {
            "date": _as_text(game.get("date")) if isinstance(game, dict) else None,
            "opponent": _as_text(game.get("opponent", {}).get("displayName"))
            if isinstance(game, dict) and isinstance(game.get("opponent"), dict)
            else None,
            "result": _as_text(game_info) if game_info else None,
        }
        for label, value in zip(labels, stats, strict=False):
            label_text = _as_text(label)
            if label_text:
                record[label_text] = _to_float(value) if _to_float(value) is not None else value
        per_game.append(record)
    return per_game[-max(1, games) :]


def _averages(per_game: list[dict[str, Any]]) -> dict[str, float]:
    """Numeric per-stat averages across the game-log window."""
    totals: dict[str, list[float]] = {}
    for game in per_game:
        for key, value in game.items():
            if key in {"date", "opponent", "result"}:
                continue
            number = _to_float(value)
            if number is not None:
                totals.setdefault(key, []).append(number)
    return {key: round(statistics.fmean(vals), 2) for key, vals in totals.items() if vals}


def _season_average(payload: dict[str, Any], stat_label: str) -> float | None:
    """Season-average for one stat label from the gamelog payload, if present."""
    season = payload.get("season")
    if not isinstance(season, dict):
        return None
    labels = season.get("labels")
    stats = season.get("statistics") or season.get("stats")
    if not isinstance(labels, list) or not isinstance(stats, list):
        return None
    for label, value in zip(labels, stats, strict=False):
        if _as_text(label) == stat_label:
            return _to_float(value)
    return None


def _trend_flag(recent_avg: float | None, season_avg: float | None, threshold: float = 0.08) -> str:
    """Hot / cold / steady flag from recent-vs-season average delta."""
    if recent_avg is None or season_avg is None or season_avg == 0:
        return "steady"
    delta = (recent_avg - season_avg) / abs(season_avg)
    if delta >= threshold:
        return "hot"
    if delta <= -threshold:
        return "cold"
    return "steady"


async def _resolve_athlete(
    name: str, espn_sport: str, espn_league: str
) -> tuple[str, str | None] | None:
    """Resolve a player name to (athlete_id, team_name) via ESPN search."""
    payload = await fetch_json(
        ESPN_SEARCH,
        {
            "query": name,
            "type": "player",
            "sport": espn_sport,
            "league": espn_league,
            "limit": "5",
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
                if isinstance(rel, dict) and _as_text(rel.get("displayName")):
                    team = _as_text(rel.get("displayName"))
                    break
        return athlete_id, team
    return None


async def get_player_recent_stats(
    player_name: str, sport: str = "nba", games: int = 10
) -> dict[str, Any]:
    """Last N games of stats for a player, with averages and hot/cold trend.

    Args:
        player_name: Player name (e.g. ``"LeBron James"``).
        sport: Sport slug (``nba``, ``nfl``, ...).
        games: Number of recent games (1-30, default 10).

    Returns:
        A dict::

            {
                "player": "LeBron James",
                "sport": "nba",
                "games_requested": 10,
                "games_found": 10,
                "per_game": [
                    {"date": "...", "opponent": "...", "result": "W 112-108",
                     "PTS": 27.0, "REB": 8.0, "AST": 6.0, "MIN": 35.0, ...},
                    ...
                ],
                "averages": {"PTS": 25.4, "REB": 7.8, ...},
                "trend": {"PTS": "hot", "REB": "steady", ...},
                "source": "espn",
            }

        ``{}`` on failure or unknown player. Never raises.
    """
    try:
        return await _get_player_recent_stats(player_name, sport, games)
    except Exception:
        logger.exception(
            "sports_player_intel_recent_stats_crashed",
            extra={"player": player_name, "sport": sport},
        )
        return {}


async def _get_player_recent_stats(player_name: str, sport: str, games: int) -> dict[str, Any]:
    name = str(player_name or "").strip()
    if not name:
        return {}
    slug = _resolve_one(sport)
    espn = _espn_pair(slug) if slug else None
    if espn is None:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return {}
    espn_sport, espn_league = espn
    found = await _resolve_athlete(name, espn_sport, espn_league)
    if found is None:
        return {}
    athlete_id, team = found
    clamped = max(1, min(int(games), 30))
    payload = await fetch_json(
        ESPN_GAMELOG.format(sport=espn_sport, league=espn_league, id=athlete_id)
    )
    if not isinstance(payload, dict):
        return {}
    per_game = _parse_gamelog(payload, clamped)
    averages = _averages(per_game)
    trend: dict[str, str] = {}
    for stat_label, recent_avg in averages.items():
        season_avg = _season_average(payload, stat_label)
        trend[stat_label] = _trend_flag(recent_avg, season_avg)
    return {
        "player": name,
        "team": team,
        "sport": _short_slug(slug),
        "games_requested": clamped,
        "games_found": len(per_game),
        "per_game": per_game,
        "averages": averages,
        "trend": trend,
        "source": "espn",
    }


# ── 4. Streaks ─────────────────────────────────────────────────────────
_STREAK_STATS: dict[str, tuple[str, ...]] = {
    "nba": ("PTS", "REB", "AST", "FGM", "FG3M", "MIN"),
    "wnba": ("PTS", "REB", "AST"),
    "nfl": ("PASSYDS", "RUSHYDS", "RECYDS", "TD"),
    "mlb": ("H", "HR", "RBI", "SO"),
    "nhl": ("G", "A", "SOG", "PIM"),
}


def _compute_streaks(
    per_game: list[dict[str, Any]],
    averages: dict[str, float],
    season_averages: dict[str, float],
) -> dict[str, Any]:
    """Condense a game log into streak / trend records.

    ``current_streak`` counts consecutive games (newest first) above
    (``hot``) or below (``cold``) the season average for the player's
    primary stat; ``prop_trend`` counts overs/unders hit versus the
    season average across the tracked stats.
    """
    primary = next((label for label in ("PTS", "PASSYDS", "H", "G") if label in averages), None)
    if not averages:
        primary = None
    current_streak: dict[str, Any] = {"type": "none", "games": 0, "stat": primary}
    if primary and primary in season_averages and per_game:
        season_avg = season_averages[primary]
        streak_type: str | None = None
        count = 0
        for game in reversed(per_game):  # newest first
            value = _to_float(game.get(primary))
            if value is None or season_avg == 0:
                break
            direction = "hot" if value > season_avg else "cold"
            if streak_type is None:
                streak_type = direction
            elif direction != streak_type:
                break
            count += 1
        if streak_type and count >= 2:
            current_streak = {"type": streak_type, "games": count, "stat": primary}

    avg_vs_season: dict[str, dict[str, float | str]] = {}
    for stat_label, recent in averages.items():
        season = season_averages.get(stat_label)
        if season is None:
            continue
        avg_vs_season[stat_label] = {
            "recent": recent,
            "season": season,
            "delta": round(recent - season, 2),
            "flag": _trend_flag(recent, season),
        }

    overs = unders = total = 0
    for stat_label, season in season_averages.items():
        if season is None or season == 0:
            continue
        for game in per_game:
            value = _to_float(game.get(stat_label))
            if value is None:
                continue
            total += 1
            if value > season:
                overs += 1
            elif value < season:
                unders += 1
    if total:
        over_rate = overs / total
        prop_trend = "over" if over_rate >= 0.6 else "under" if over_rate <= 0.4 else "mixed"
    else:
        over_rate = None
        prop_trend = "unknown"

    return {
        "current_streak": current_streak,
        "avg_vs_season": avg_vs_season,
        "prop_trend": prop_trend,
        "over_rate": round(over_rate, 2) if over_rate is not None else None,
        "games_sampled": total,
    }


async def get_player_streaks(player_name: str, sport: str = "nba") -> dict[str, Any]:
    """Hot/cold streak detection for a player versus season averages.

    Args:
        player_name: Player name (e.g. ``"LeBron James"``).
        sport: Sport slug (``nba``, ``nfl``, ...).

    Returns:
        A dict::

            {
                "player": "LeBron James",
                "sport": "nba",
                "current_streak": {"type": "hot", "games": 4, "stat": "PTS"},
                "avg_vs_season": {
                    "PTS": {"recent": 28.1, "season": 25.4, "delta": 2.7,
                            "flag": "hot"},
                    ...
                },
                "prop_trend": "over",   # over / under / mixed / none
                "over_rate": 0.68,      # share of games above season avg
                "games_sampled": 57,
                "source": "espn",
            }

        ``{}`` on failure or unknown player. Never raises.
    """
    try:
        return await _get_player_streaks(player_name, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_streaks_crashed",
            extra={"player": player_name, "sport": sport},
        )
        return {}


async def _get_player_streaks(player_name: str, sport: str) -> dict[str, Any]:
    name = str(player_name or "").strip()
    if not name:
        return {}
    slug = _resolve_one(sport)
    espn = _espn_pair(slug) if slug else None
    if espn is None:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return {}
    espn_sport, espn_league = espn
    found = await _resolve_athlete(name, espn_sport, espn_league)
    if found is None:
        return {}
    athlete_id, team = found
    payload = await fetch_json(
        ESPN_GAMELOG.format(sport=espn_sport, league=espn_league, id=athlete_id)
    )
    if not isinstance(payload, dict):
        return {}
    per_game = _parse_gamelog(payload, 30)
    averages = _averages(per_game)
    season_averages = {
        label: value for label in averages if (value := _season_average(payload, label)) is not None
    }
    result = _compute_streaks(per_game, averages, season_averages)
    result.update(
        {
            "player": name,
            "team": team,
            "sport": _short_slug(slug),
            "source": "espn",
        }
    )
    return result


# ── 5. Team-wide props ─────────────────────────────────────────────────
async def get_team_player_props(team: str, sport: str = "nba") -> list[dict[str, Any]]:
    """All player props for every player on a team's next event.

    Args:
        team: Team name (e.g. ``"Lakers"``).
        sport: Sport slug (``nba``, ``nfl``, ...).

    Returns:
        A list of prop records for every player on the team with a live
        line, one per (player, market, book)::

            {
                "player": "LeBron James",
                "team": "Los Angeles Lakers",
                "sport": "nba",
                "prop_type": "player_points",
                "line": 25.5,
                "over_odds": 1.91,
                "under_odds": 1.95,
                "book": "DraftKings",
                "movement": "steady",
                "source": "the_odds_api",
            }

        ``[]`` on failure, unknown team, or no Odds API key (ESPN publishes
        no team-level props feed). Never raises.
    """
    try:
        return await _get_team_player_props(team, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_team_props_crashed", extra={"team": team, "sport": sport}
        )
        return []


async def _get_team_player_props(team: str, sport: str) -> list[dict[str, Any]]:
    name = str(team or "").strip()
    if not name:
        return []
    slug = _resolve_one(sport)
    if not slug:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return []
    key = api_key()
    if not key:
        return []
    resolved = await _resolve_team(name, slug)
    if resolved is None:
        return []
    event, competitor, _espn_sport, _espn_league = resolved
    event_id = _as_text(event.get("id"))
    if not event_id:
        return []
    team_obj = competitor.get("team")
    team_name = _as_text(team_obj.get("displayName")) if isinstance(team_obj, dict) else None
    market_keys = list(_PROP_MARKETS.get(_short_slug(slug), []))
    if not market_keys:
        return []
    odds_key, _espn = _SPORTS[slug]
    payload = await fetch_json(
        f"{ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds",
        {
            "apiKey": key,
            "regions": ODDS_API_REGIONS,
            "markets": ",".join(market_keys),
            "oddsFormat": "decimal",
        },
    )
    if not isinstance(payload, dict):
        return []
    records = _map_all_player_props(payload, slug, team_name)
    return _annotate_movement(records)


def _map_all_player_props(
    raw: dict[str, Any], slug: str, team_name: str | None
) -> list[dict[str, Any]]:
    """Map one Odds API event payload to prop records for every player."""
    bookmakers = raw.get("bookmakers")
    if not isinstance(bookmakers, list):
        return []
    records: list[dict[str, Any]] = []
    for bk in bookmakers:
        if not isinstance(bk, dict):
            continue
        book = _as_text(bk.get("title")) or _as_text(bk.get("key"))
        markets = bk.get("markets")
        if not book or not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            market_key = _as_text(mkt.get("key")) or ""
            if not market_key.startswith("player_"):
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
                        "team": team_name,
                        "sport": _short_slug(slug),
                        "prop_type": market_key,
                        "market": market_key,
                        "line": point,
                        "over_odds": over,
                        "under_odds": under,
                        "book": book,
                        "source": "the_odds_api",
                    }
                )
    return records


# ── 6. Matchup props with defensive context ────────────────────────────
def _defense_grade(rank: int | None) -> str | None:
    """Human defensive grade from a league rank (1 = best defense)."""
    if rank is None:
        return None
    if rank <= 8:
        return "tough"
    if rank >= 22:
        return "soft"
    return "average"


async def _team_defensive_ranks(
    team_id: str | None, espn_sport: str, espn_league: str
) -> dict[str, int | None]:
    """Best-effort defensive rank context for one team (per stat category).

    ESPN's public team-stats feed exposes opponent categories; ranks are
    derived by comparing the team's opponent average against the league
    scoreboard teams is out of scope here — we return the raw opponent
    stats and let the caller annotate. Returns a label -> rank map where
    ranks are approximated from the team's defensive stats when present.
    """
    if not team_id:
        return {}
    payload = await fetch_json(
        ESPN_TEAM_STATS.format(sport=espn_sport, league=espn_league, team_id=team_id)
    )
    if not isinstance(payload, dict):
        return {}
    ranks: dict[str, int | None] = {}
    categories = payload.get("categories")
    if not isinstance(categories, list):
        return ranks
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        display_names = cat.get("displayNames")
        statistics_list = cat.get("statistics")
        if (
            isinstance(display_names, list)
            and isinstance(statistics_list, list)
            and statistics_list
        ):
            latest = statistics_list[-1]
            if isinstance(latest, dict) and isinstance(latest.get("stats"), list):
                for label, _value, rank in zip(
                    display_names, latest["stats"], latest.get("perGameRanks", []), strict=False
                ):
                    label_text = _as_text(label)
                    rank_value = _to_float(rank)
                    if label_text and rank_value is not None:
                        ranks[label_text] = int(rank_value)
    return ranks


async def get_props_vs_matchup(
    home_team: str, away_team: str, sport: str = "nba"
) -> dict[str, Any]:
    """All player props for a matchup, with defensive-ranking context.

    Args:
        home_team: Home team name (e.g. ``"Lakers"``).
        away_team: Away team name (e.g. ``"Celtics"``).
        sport: Sport slug (``nba``, ``nfl``, ...).

    Returns:
        A dict::

            {
                "sport": "nba",
                "event": "Celtics @ Lakers",
                "event_id": "401772301",
                "home_team": "Los Angeles Lakers",
                "away_team": "Boston Celtics",
                "props": [ ...prop records for both teams... ],
                "defense": {
                    "Los Angeles Lakers": {
                        "player_points": {"rank": 5, "grade": "tough"},
                        ...
                    },
                    ...
                },
                "source": "the_odds_api",
            }

        ``{}`` on failure, unknown teams, or no Odds API key. Never raises.
    """
    try:
        return await _get_props_vs_matchup(home_team, away_team, sport)
    except Exception:
        logger.exception(
            "sports_player_intel_matchup_crashed",
            extra={"home": home_team, "away": away_team, "sport": sport},
        )
        return {}


async def _get_props_vs_matchup(home_team: str, away_team: str, sport: str) -> dict[str, Any]:
    home = str(home_team or "").strip()
    away = str(away_team or "").strip()
    if not home or not away:
        return {}
    slug = _resolve_one(sport)
    espn = _espn_pair(slug) if slug else None
    if espn is None:
        logger.warning("sports_player_intel_invalid_sport", extra={"sport": sport})
        return {}
    espn_sport, espn_league = espn
    scoreboard = await fetch_json(ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league))
    if not isinstance(scoreboard, dict):
        return {}
    event = _find_matchup_event(scoreboard, home, away)
    if event is None:
        return {}
    competitors = _event_competitors(event)
    if len(competitors) < 2:
        return {}

    def _team_label(competitor: dict[str, Any]) -> str | None:
        team_obj = competitor.get("team")
        if isinstance(team_obj, dict):
            return _as_text(team_obj.get("displayName")) or _as_text(team_obj.get("name"))
        return None

    home_name = _team_label(competitors[0]) or home
    away_name = _team_label(competitors[1]) or away
    event_id = _as_text(event.get("id"))
    if not event_id:
        return {}

    key = api_key()
    market_keys = list(_PROP_MARKETS.get(_short_slug(slug), []))
    records: list[dict[str, Any]] = []
    if key and market_keys:
        odds_key, _espn = _SPORTS[slug]
        payload = await fetch_json(
            f"{ODDS_BASE}/{quote(odds_key)}/events/{quote(event_id)}/odds",
            {
                "apiKey": key,
                "regions": ODDS_API_REGIONS,
                "markets": ",".join(market_keys),
                "oddsFormat": "decimal",
            },
        )
        if isinstance(payload, dict):
            records = _map_all_player_props(payload, slug, None)
            records = _annotate_movement(records)

    # Defensive context per team from ESPN team stats (best effort).
    defense: dict[str, dict[str, dict[str, Any]]] = {}
    for competitor, label in ((competitors[0], home_name), (competitors[1], away_name)):
        team_obj = competitor.get("team")
        team_id = _as_text(team_obj.get("id")) if isinstance(team_obj, dict) else None
        ranks = await _team_defensive_ranks(team_id, espn_sport, espn_league)
        context: dict[str, dict[str, Any]] = {}
        for market_key in _defense_markets(slug):
            rank = _match_defense_rank(market_key, ranks)
            if rank is not None:
                context[market_key] = {"rank": rank, "grade": _defense_grade(rank)}
        defense[label or ""] = context

    return {
        "sport": _short_slug(slug),
        "event": f"{away_name} @ {home_name}",
        "event_id": event_id,
        "home_team": home_name,
        "away_team": away_name,
        "props": records,
        "defense": defense,
        "source": "the_odds_api" if records else "espn",
    }


def _defense_markets(slug: str) -> tuple[str, ...]:
    """Core prop markets to annotate with defensive context for a sport."""
    return _DEFENSE_MARKETS.get(_short_slug(slug), ())


def _match_defense_rank(market_key: str, ranks: dict[str, int | None]) -> int | None:
    """Best-effort defensive rank for a prop market from ESPN stat labels."""
    fragment = market_key.removeprefix("player_").replace("_", " ").casefold()
    for label, rank in ranks.items():
        if rank is None:
            continue
        if fragment and fragment in label.casefold():
            return rank
    return None
