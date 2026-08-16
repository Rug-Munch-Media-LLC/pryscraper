"""Injuries — ESPN public injury feeds + best-effort team-site scrape fallback.

Two sources are aggregated here:

* **ESPN injury feeds** (``site.api.espn.com/apis/site/v2/sports/.../injuries``)
  — no auth, no quota. Emits one ``athletes[]`` entry per injured player with
  an ``injury`` block (``status``, ``type``/``typeDetail``, ``returnDate``).
  This is the primary source for every league ESPN covers.
* **Team-site scrape** — when a *specific* team is requested and the JSON
  feed yields no matches (league not covered, feed empty, or 403), the
  module makes one best-effort GET of ESPN's team injuries HTML page
  (``https://www.espn.com/{league}/team/injuries/_/name/{abbr}``) and
  extracts table rows with a minimal stdlib HTMLParser. The page structure
  is not a stable API — treat it as a last-resort fallback; failures
  degrade to ``[]``.

Contract
--------
* :func:`get_injuries` — async, never raises, returns a ``list`` (``[]`` on
  failure). One record per injured player.
* :func:`get_injury_report` — async, never raises, returns a ``list``.
  Resolves a game id to its two teams via the ESPN scoreboard, then returns
  the injuries for those teams (``[]`` for unknown games / errors).

Result shapes
-------------
``get_injuries`` returns a list of:

    {
        "player": "LeBron James",
        "team": "Los Angeles Lakers",
        "status": "out",
        "injury": "Foot",
        "return_estimate": "2026-09-01T00:00:00Z",
        "sport": "nba",
        "source": "espn",
    }

``status`` is normalized to one of ``"questionable"`` / ``"out"`` / ``"IR"``
/ ``"unknown"``: ESPN's ``Out``/``Out for season``/``Out indefinitely`` →
``out``; ``IR``/``Injured Reserve`` → ``IR``; ``Questionable``,
``Day-To-Day``, ``Doubtful`` and ``Probable`` → ``questionable``. ``injury``
is ESPN's body-part label (e.g. ``"Foot"``) or the free-text detail, and
``return_estimate`` is ESPN's ``returnDate`` (``None`` when unknown).

Sport names match :mod:`sports_data.odds`. ``team`` filters case-insensitively
(substring or whole-token) against the team display name; ``"all"`` (default)
returns every team. Backoff: 1 retry, exponential (0.1s -> 0.4s).

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
from html.parser import HTMLParser
from typing import Any

import httpx

from retry import RetryConfig, async_retry
from sports_data.odds import _SPORTS, _resolve_sports

logger = logging.getLogger(__name__)

_ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/injuries"
_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
_ESPN_TEAM_INJURIES_HTML = "https://www.espn.com/{league}/team/injuries/_/name/{abbr}"

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

# Raw ESPN status text -> canonical bucket. Longer/specific phrases first so
# e.g. "out for season" is matched before the bare "out" token.
_STATUS_BUCKETS: dict[str, str] = {
    "out for season": "out",
    "out for career": "out",
    "out indefinitely": "out",
    "out": "out",
    "injured reserve": "IR",
    "ir": "IR",
    "day-to-day": "questionable",
    "questionable": "questionable",
    "doubtful": "questionable",
    "probable": "questionable",
}


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_status(raw: Any) -> str:
    """Map an ESPN injury status string onto a canonical status bucket."""
    text = str(raw or "").strip().lower().replace("_", " ").replace("-", " ")
    text = " ".join(text.split())
    if not text:
        return "unknown"
    for phrase, bucket in _STATUS_BUCKETS.items():
        if phrase in text:
            return bucket
    return "unknown"


# ── Fetching ───────────────────────────────────────────────────────────
async def _fetch_json(url: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return the parsed JSON object, or ``None`` on failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("ESPN injuries payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_text(url: str) -> str | None:
    """GET ``url`` and return the raw text body, or ``None`` on failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


# ── ESPN JSON mapping ──────────────────────────────────────────────────
def _map_injuries(payload: dict[str, Any], sport_slug: str) -> list[dict[str, Any]]:
    """Map an ESPN ``injuries`` payload onto canonical injury records."""
    athletes = payload.get("athletes")
    if not isinstance(athletes, list):
        return []
    records: list[dict[str, Any]] = []
    for athlete in athletes:
        if not isinstance(athlete, dict):
            continue
        player = _as_text(athlete.get("fullName")) or _as_text(athlete.get("displayName"))
        if not player:
            continue
        team_obj = athlete.get("team")
        team = _as_text(team_obj.get("displayName")) if isinstance(team_obj, dict) else None
        team = team or _as_text(athlete.get("teamName"))
        if not team:
            continue
        injury = athlete.get("injury")
        status = _normalize_status(
            injury.get("status") if isinstance(injury, dict) else athlete.get("status")
        )
        injury_text: str | None = None
        return_estimate: str | None = None
        if isinstance(injury, dict):
            injury_text = (
                _as_text(injury.get("typeDetail"))
                or _as_text(injury.get("type"))
                or _as_text(injury.get("detail"))
            )
            return_estimate = _as_text(injury.get("returnDate"))
        records.append(
            {
                "player": player,
                "team": team,
                "status": status,
                "injury": injury_text,
                "return_estimate": return_estimate,
                "sport": sport_slug,
                "source": "espn",
            }
        )
    return records


async def _espn_injuries_for_league(
    espn_sport: str, espn_league: str, sport_slug: str
) -> list[dict[str, Any]]:
    """Fetch one league's ESPN injuries feed and map it to records."""
    url = _ESPN_INJURIES.format(sport=espn_sport, league=espn_league)
    payload = await _fetch_json(url)
    if not isinstance(payload, dict):
        return []
    return _map_injuries(payload, sport_slug)


def _team_matches(team_name: str | None, team_query: str) -> bool:
    """Case-insensitive team filter: substring or whole-token match."""
    query = str(team_query or "").strip().casefold()
    if not query or query == "all":
        return True
    if not team_name:
        return False
    name = team_name.casefold()
    return query in name or any(token == query for token in name.split())


# ── Team-site scrape fallback ──────────────────────────────────────────
class _InjuryRowParser(HTMLParser):
    """Collect table rows from an ESPN team injuries HTML page (best-effort)."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._cells: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._cells = []
        elif tag in {"td", "th"}:
            self._in_cell = True
            self._cells.append("")

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._cells:
            self._cells[-1] += data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            self._in_cell = False
        elif tag == "tr":
            self.rows.append([cell.strip() for cell in self._cells])
            self._cells = []


def _parse_team_page(html: str) -> list[dict[str, Any]]:
    """Parse player/status/comment rows out of a team injuries HTML page.

    Rows look like ``[player, status, comment, ...]``; rows without a
    recognizable status keyword are skipped. Team/sport are unknown here and
    left ``None`` / ``"unknown"`` for the caller to fill in.
    """
    parser = _InjuryRowParser()
    parser.feed(html)
    records: list[dict[str, Any]] = []
    for row in parser.rows:
        if len(row) < 2:
            continue
        player = row[0].strip()
        if not player:
            continue
        status = _normalize_status(row[1])
        if status == "unknown":
            continue
        injury_text = row[2].strip() if len(row) > 2 and row[2] else None
        records.append(
            {
                "player": player,
                "team": None,
                "status": status,
                "injury": injury_text,
                "return_estimate": None,
                "sport": "unknown",
                "source": "team_site",
            }
        )
    return records


def _abbreviation(team_query: str) -> str | None:
    """Best-effort ESPN team-page abbreviation for a team query."""
    text = str(team_query or "").strip()
    if not text:
        return None
    if text.isupper() and len(text) <= 4:
        return text.lower()
    return text[:3].lower()


async def _scrape_team_injuries(espn_league: str, team_query: str) -> list[dict[str, Any]]:
    """Best-effort team-site scrape for one team's injuries."""
    abbr = _abbreviation(team_query)
    if not abbr:
        return []
    url = _ESPN_TEAM_INJURIES_HTML.format(league=espn_league, abbr=abbr)
    html = await _fetch_text(url)
    if not html:
        return []
    return _parse_team_page(html)


# ── Public API ─────────────────────────────────────────────────────────
async def get_injuries(sport: str, team: str = "all") -> list[dict[str, Any]]:
    """Fetch injuries for one or more sports.

    Args:
        sport: Sport name (see module docstring) or ``"all"`` (default).
        team: Team filter (case-insensitive substring / token) or
            ``"all"`` (default). A specific team that yields no JSON feed
            matches triggers the team-site scrape fallback.

    Returns:
        A list of injury records (see module docstring). ``[]`` on failure
        or invalid sport. Never raises.
    """
    try:
        return await _get_injuries(sport, team)
    except Exception:
        logger.exception("sports_injuries_crashed", extra={"sport": sport, "team": team})
        return []


async def _get_injuries(sport: str, team: str) -> list[dict[str, Any]]:
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_injuries_invalid_sport", extra={"sport": sport})
        return []
    query = str(team or "all").strip()
    records: list[dict[str, Any]] = []
    for slug in slugs:
        espn = _SPORTS[slug][1]
        if espn is None:
            continue
        espn_sport, espn_league = espn
        league_records = await _espn_injuries_for_league(espn_sport, espn_league, slug)
        league_records = [
            record for record in league_records if _team_matches(record.get("team"), query)
        ]
        if not league_records and query and query != "all":
            league_records = await _scrape_team_injuries(espn_league, query)
        records.extend(league_records)
        if len(records) >= _MAX_LIMIT:
            break
    return records[:_MAX_LIMIT]


async def get_injury_report(game_id: str) -> list[dict[str, Any]]:
    """Fetch the injury report for a single game.

    Args:
        game_id: The game id. Accepts an optional ``sport:game_id`` prefix
            (e.g. ``nba:401765432``) to skip the default-sport scan.

    Returns:
        A list of injury records for the game's two teams. ``[]`` on
        failure (unknown game, network error). Never raises.
    """
    try:
        return await _get_injury_report(game_id)
    except Exception:
        logger.exception("sports_injury_report_crashed", extra={"game_id": game_id})
        return []


async def _game_teams(espn_sport: str, espn_league: str, target_id: str) -> list[str]:
    """Resolve a game id on an ESPN scoreboard to its team display names."""
    url = _ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league)
    payload = await _fetch_json(url)
    if not isinstance(payload, dict):
        return []
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if _as_text(ev.get("id")) != target_id:
            continue
        competitions = ev.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            return []
        comp = competitions[0]
        if not isinstance(comp, dict):
            return []
        teams: list[str] = []
        competitors = comp.get("competitors")
        if isinstance(competitors, list):
            for c in competitors:
                if not isinstance(c, dict):
                    continue
                team_obj = c.get("team")
                name = _as_text(team_obj.get("displayName")) if isinstance(team_obj, dict) else None
                if name:
                    teams.append(name)
        return teams
    return []


async def _get_injury_report(game_id: str) -> list[dict[str, Any]]:
    if not game_id or not str(game_id).strip():
        return []
    raw_id = str(game_id).strip()
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
    for slug in candidates:
        espn = _SPORTS[slug][1]
        if espn is None:
            continue
        espn_sport, espn_league = espn
        teams = await _game_teams(espn_sport, espn_league, target_id)
        if not teams:
            continue
        url = _ESPN_INJURIES.format(sport=espn_sport, league=espn_league)
        payload = await _fetch_json(url)
        if not isinstance(payload, dict):
            continue
        records = [
            record
            for record in _map_injuries(payload, slug)
            if any(_team_matches(record.get("team"), t) for t in teams)
        ]
        return records
    return []
