"""Live in-game intelligence — ESPN live scoreboards, mid-game analytics.

Free public ESPN scoreboard API (no key, no quota). All functions are
async, never raise, and return ``{}`` / ``[]`` on any failure. Parsing is
fully defensive: ESPN payloads vary by sport and some egress IPs get 403.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
_TIMEOUT = httpx.Timeout(10.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

# sport slug -> (espn sport path, espn league path)
_SPORTS: dict[str, tuple[str, str]] = {
    "nba": ("basketball", "nba"),
    "wnba": ("basketball", "wnba"),
    "ncaab": ("basketball", "mens-college-basketball"),
    "nfl": ("football", "nfl"),
    "ncaaf": ("football", "college-football"),
    "mlb": ("baseball", "mlb"),
    "nhl": ("hockey", "nhl"),
    "epl": ("soccer", "eng.1"),
    "mls": ("soccer", "usa.1"),
    "cfl": ("football", "cfl"),
}


def _slug(sport: str) -> str:
    """Map a sport name to its ESPN slug (default nba)."""
    return _SPORTS.get((sport or "nba").strip().lower(), _SPORTS["nba"])


async def _fetch_json(url: str) -> dict[str, Any]:
    """GET ``url`` -> parsed JSON dict, or ``{}`` on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.debug("espn live fetch failed: %s", exc)
        return {}


async def _scoreboard(sport: str) -> dict[str, Any]:
    """Fetch one league's ESPN scoreboard (or ``{}``)."""
    espn_sport, espn_league = _SPORTS.get((sport or "nba").strip().lower(), _SPORTS["nba"])
    return await _fetch_json(_ESPN_SCOREBOARD.format(sport=espn_sport, league=espn_league))


def _events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Scoreboard event list (defensive)."""
    events = payload.get("events")
    return [e for e in events if isinstance(e, dict)] if isinstance(events, list) else []


def _find_event(payload: dict[str, Any], event_id: str) -> dict[str, Any]:
    """Locate one event by id in a scoreboard payload."""
    for ev in _events(payload):
        if str(ev.get("id")) == str(event_id) or str(ev.get("uid", "")).endswith(str(event_id)):
            return ev
    return {}


def _competition(ev: dict[str, Any]) -> dict[str, Any]:
    """Event's first competition (defensive)."""
    comps = ev.get("competitions")
    if isinstance(comps, list) and comps and isinstance(comps[0], dict):
        return comps[0]
    return {}


def _competitors(comp: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """home/away -> competitor dict."""
    return {
        str(side["homeAway"]): side
        for side in comp.get("competitors") or []
        if isinstance(side, dict) and side.get("homeAway") in ("home", "away")
    }


def _team(side: dict[str, Any]) -> dict[str, Any]:
    """team name/abbr/score from a competitor."""
    team = side.get("team") if isinstance(side.get("team"), dict) else {}
    return {
        "name": team.get("displayName") or team.get("name"),
        "abbr": team.get("abbreviation"),
        "score": _num(side.get("score")),
    }


def _num(value: Any) -> float | None:
    """JSON value -> float/None."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status(ev: dict[str, Any], comp: dict[str, Any]) -> dict[str, Any]:
    """quarter, clock, state, description from status."""
    for source in (comp, ev):
        status = source.get("status")
        st = status.get("type") if isinstance(status, dict) else None
        if isinstance(st, dict):
            return {
                "state": st.get("state"),
                "description": st.get("description") or st.get("shortDetail"),
                "period": st.get("period") or 0,
                "clock": st.get("shortDetail") or st.get("displayClock"),
                "completed": bool(st.get("completed")),
            }
    return {"state": None, "description": None, "period": 0, "clock": None, "completed": False}


def _odds_block(comp: dict[str, Any]) -> dict[str, Any]:
    """First odds provider block or ``{}``."""
    odds = comp.get("odds")
    return odds[0] if isinstance(odds, list) and odds and isinstance(odds[0], dict) else {}


def _pace(home: dict[str, Any], away: dict[str, Any], period: int, clock: str) -> dict[str, Any]:
    """Pace (pts/min) + projected final total."""
    total = (home.get("score") or 0) + (away.get("score") or 0)
    minutes_left = _minutes_left(period, clock)
    minutes_played = max(_REGULATION_MINUTES - minutes_left, 1.0)
    rate = total / minutes_played
    projected = round(total + rate * minutes_left, 1) if minutes_left > 0 else total
    return {
        "points_per_minute": round(rate, 2),
        "minutes_elapsed": round(minutes_played, 1),
        "minutes_remaining": round(minutes_left, 1),
        "projected_total": projected,
    }


_REGULATION_MINUTES = 48.0  # NBA default; other sports approximate


def _minutes_left(period: int, clock: str) -> float:
    """Minutes remaining from period + clock."""
    remaining = 12.0
    if isinstance(clock, str) and ":" in clock:
        try:
            mins, secs = clock.split(":")[-2:]
            remaining = int(mins) + int(secs) / 60.0
        except (ValueError, IndexError):
            pass
    return max(min((4 - period) * 12.0 + remaining, _REGULATION_MINUTES), 0.0)


def _win_prob(home_score: float, away_score: float, minutes_left: float) -> float:
    """Home win prob from lead vs time left."""
    lead = home_score - away_score
    if minutes_left <= 0:
        return 1.0 if lead > 0 else (0.0 if lead < 0 else 0.5)
    # ~4.5% win-prob swing per point-per-minute of lead, capped.
    prob = 0.5 + (lead / max(minutes_left, 1.0)) * 0.045
    return round(min(max(prob, 0.01), 0.99), 3)


# ── Public API ────────────────────────────────────────────────────────
async def get_live_games(sport: str = "nba") -> list[dict[str, Any]]:
    """Every in-progress game: id, teams, score, quarter, clock, status."""
    payload = await _scoreboard(sport)
    out: list[dict[str, Any]] = []
    for ev in _events(payload):
        comp = _competition(ev)
        sides = _competitors(comp)
        status = _status(ev, comp)
        if status.get("state") != "in":
            continue
        home, away = _team(sides.get("home", {})), _team(sides.get("away", {}))
        out.append(
            {
                "sport": sport,
                "event_id": str(ev.get("id") or ""),
                "event": ev.get("name") or ev.get("shortName"),
                "home": home["name"],
                "away": away["name"],
                "home_score": home["score"],
                "away_score": away["score"],
                "quarter": status["period"],
                "time_remaining": status["clock"],
                "status": status["description"],
            }
        )
    return out


async def get_live_game_state(event_id: str, sport: str = "nba") -> dict[str, Any]:
    """Score, quarter, time, possession, momentum, pace, rate, timeouts."""
    payload = await _scoreboard(sport)
    ev = _find_event(payload, event_id)
    if not ev:
        return {}
    comp = _competition(ev)
    sides = _competitors(comp)
    home, away = _team(sides.get("home", {})), _team(sides.get("away", {}))
    status = _status(ev, comp)
    sit = comp.get("situation")
    sit = sit if isinstance(sit, dict) else {}
    pace = _pace(home, away, status["period"], status["clock"] or "")
    last_five = sit.get("lastFivePlays")
    return {
        "event_id": str(ev.get("id") or ""),
        "event": ev.get("name"),
        "home": home,
        "away": away,
        "quarter": status["period"],
        "time_remaining": status["clock"],
        "status": status["description"],
        "possession": sit.get("possession") or sit.get("possessionText"),
        "momentum": {
            "last_five_possessions": last_five if isinstance(last_five, list) else [],
            "down": sit.get("down"),
            "distance": sit.get("distance"),
            "yard_line": sit.get("yardLine"),
        },
        "pace": pace,
        "scoring_rate": pace["points_per_minute"],
        "timeouts": {
            "home": _num(sides.get("home", {}).get("timeouts")),
            "away": _num(sides.get("away", {}).get("timeouts")),
        },
    }


async def get_live_win_probability(event_id: str, sport: str = "nba") -> dict[str, Any]:
    """Home/away win prob, projections, total, over/spread probabilities."""
    payload = await _scoreboard(sport)
    ev = _find_event(payload, event_id)
    if not ev:
        return {}
    comp = _competition(ev)
    sides = _competitors(comp)
    home, away = _team(sides.get("home", {})), _team(sides.get("away", {}))
    status = _status(ev, comp)
    minutes_left = _minutes_left(status["period"], status["clock"] or "")
    wp_list = comp.get("winProbability")
    espn_wp = (
        _num(wp_list[-1].get("homeWinPercentage"))
        if (isinstance(wp_list, list) and wp_list and isinstance(wp_list[0], dict))
        else None
    )
    home_prob = (
        espn_wp
        if espn_wp is not None
        else _win_prob(home.get("score") or 0.0, away.get("score") or 0.0, minutes_left)
    )
    pace = _pace(home, away, status["period"], status["clock"] or "")
    proj_total = pace["projected_total"]
    margin = (home.get("score") or 0.0) - (away.get("score") or 0.0)
    proj_home = round((proj_total + margin) / 2, 1)
    ou = _num(_odds_block(comp).get("overUnder"))
    return {
        "event_id": str(ev.get("id") or ""),
        "home_win_probability": round(home_prob, 3),
        "away_win_probability": round(1.0 - home_prob, 3),
        "source": "espn" if espn_wp is not None else "heuristic",
        "projected_home_score": proj_home,
        "projected_away_score": round(proj_total - proj_home, 1),
        "projected_total": proj_total,
        "over_probability": _side_prob(proj_total, ou, True),
        "under_probability": _side_prob(proj_total, ou, False),
        "spread_cover_probability": {
            "home": round(home_prob, 3),
            "away": round(1.0 - home_prob, 3),
        },
    }


def _side_prob(projected: float, line: float | None, over: bool) -> float | None:
    """Over/under prob vs a total line (None if no line)."""
    if line is None:
        return None
    prob = 0.5 + ((projected - line) / max(abs(line) or 1.0, 10.0)) * 0.5
    prob = min(max(prob, 0.02), 0.98)
    return round(prob if over else 1.0 - prob, 3)


async def get_live_scoring_breakdown(event_id: str, sport: str = "nba") -> dict[str, Any]:
    """Per-quarter scores, scoring runs, lead changes, ties."""
    payload = await _scoreboard(sport)
    ev = _find_event(payload, event_id)
    if not ev:
        return {}
    comp = _competition(ev)
    sides = _competitors(comp)
    quarters: list[dict[str, Any]] = []
    lead_changes = 0
    ties = 0
    runs: list[dict[str, Any]] = []
    prev_leader: str | None = None
    prev_margin = 0.0
    for side_key, label in (("home", "home"), ("away", "away")):
        side = sides.get(side_key, {})
        lines = side.get("linescores")
        if isinstance(lines, list):
            for idx, ls in enumerate(lines):
                val = _num(ls.get("value")) if isinstance(ls, dict) else _num(ls)
                while len(quarters) <= idx:
                    quarters.append({"period": idx + 1, "home": 0.0, "away": 0.0})
                quarters[idx][label] = val
    running_home = running_away = 0.0
    for q in quarters:
        running_home += q["home"] or 0.0
        running_away += q["away"] or 0.0
        margin = running_home - running_away
        leader = "home" if margin > 0 else ("away" if margin < 0 else None)
        if leader is None:
            ties += 1
        elif prev_leader is not None and leader != prev_leader:
            lead_changes += 1
            runs.append(
                {
                    "after_quarter": q["period"],
                    "new_leader": leader,
                    "swing": round(abs(margin - prev_margin), 1),
                }
            )
        if leader is not None:
            prev_leader = leader
        prev_margin = margin
    return {
        "event_id": str(ev.get("id") or ""),
        "event": ev.get("name"),
        "quarters": quarters,
        "lead_changes": lead_changes,
        "ties": ties,
        "scoring_runs": runs,
        "current_margin": round(prev_margin, 1),
    }


async def get_live_betting_impact(event_id: str, sport: str = "nba") -> dict[str, Any]:
    """Spread value, pace-based total projection, live arb opportunities."""
    payload = await _scoreboard(sport)
    ev = _find_event(payload, event_id)
    if not ev:
        return {}
    comp = _competition(ev)
    sides = _competitors(comp)
    home, away = _team(sides.get("home", {})), _team(sides.get("away", {}))
    status = _status(ev, comp)
    margin = (home.get("score") or 0.0) - (away.get("score") or 0.0)
    pace = _pace(home, away, status["period"], status["clock"] or "")
    odds = _odds_block(comp)
    spread = _num(odds.get("spread"))
    ou = _num(odds.get("overUnder"))
    arbs: list[dict[str, Any]] = []
    if spread is not None:
        live_spread = -margin  # home favored when margin positive
        edge = round(live_spread - spread, 1)
        if abs(edge) >= 3.0:
            arbs.append(
                {
                    "type": "spread_value",
                    "opening_spread": spread,
                    "live_spread_equivalent": live_spread,
                    "edge": edge,
                    "side": "home" if edge > 0 else "away",
                    "note": "live score has moved past the posted spread",
                }
            )
    if ou is not None and pace["projected_total"] is not None:
        total_edge = round(pace["projected_total"] - ou, 1)
        if abs(total_edge) >= 8.0:
            arbs.append(
                {
                    "type": "total_value",
                    "posted_total": ou,
                    "pace_projected_total": pace["projected_total"],
                    "edge": total_edge,
                    "side": "over" if total_edge > 0 else "under",
                }
            )
    return {
        "event_id": str(ev.get("id") or ""),
        "event": ev.get("name"),
        "current_margin": round(margin, 1),
        "posted_spread": spread,
        "posted_total": ou,
        "pace_projected_total": pace["projected_total"],
        "points_per_minute": pace["points_per_minute"],
        "arb_opportunities": arbs,
    }
