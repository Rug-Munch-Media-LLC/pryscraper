"""Settled ESPN results + moneyline open/close — the backtest's outcome source.

Why this module exists: the backtest harness needs three things per bet that the
repo did not have together — a price at bet time, a closing price, and a settled
outcome. ESPN publishes all three, keyless:

* ``site.web.api.espn.com/.../scoreboard?dates=YYYYMMDD`` — completed games with
  ``event_id``, commence ``date``, team names and final scores.
* ``sports.core.api.espn.com/v2/.../odds/<provider>`` — per-event moneyline with
  ``open`` (the price available before the game, i.e. bet time) and ``close``
  (the closing line), in decimal.

``site.api.espn.com`` (used by :mod:`sports_data.scores`) is Akamai-blocked from
this host; the ``site.web.api`` host serves the same v2 schema and answers 200.

Contract: :func:`fetch_results` returns completed games only; :func:`fetch_moneyline`
returns decimal open/close for one side. Neither invents a value — a missing
score, side or price is absent, never zero. ``derive_won`` returns ``None`` for a
tie (a push has no winner; the join refuses to guess).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

SCOREBOARD = "https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
ODDS = (
    "https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}"
    "/events/{event}/competitions/{comp}/odds/{provider}"
)
USER_AGENT = "pryscraper-backtest/1.0 (+https://rugmunch.io)"
TIMEOUT_S = 20.0
PROVIDER = "100"  # ESPN default book: DraftKings


def _get_json(url: str) -> Any:
    """Fetch one JSON document. Transport errors propagate (caller exits 2)."""
    req = urllib.request.Request(  # noqa: S310 - fixed https URL
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https hosts
        return json.loads(resp.read().decode("utf-8"))


def _competitor(comp: dict, side: str) -> dict:
    for team in comp.get("competitors") or ():
        if str(team.get("homeAway", "")).lower() == side:
            return team
    return {}


def _score(comp: dict, side: str) -> int | None:
    raw = _competitor(comp, side).get("score")
    return int(raw) if raw not in (None, "") else None


def _completed(event: dict) -> dict | None:
    """Return the competition dict when the game is final, else None."""
    comp = (event.get("competitions") or [{}])[0]
    status = (comp.get("status") or {}).get("type") or {}
    return comp if status.get("completed") else None


def _first(*values: Any) -> Any:
    for value in values:
        if value:
            return value
    return ""


def _scoreboard_row(event: dict, comp: dict) -> dict[str, Any] | None:
    home, away = _competitor(comp, "home"), _competitor(comp, "away")
    home_score, away_score = _score(comp, "home"), _score(comp, "away")
    if home_score is None or away_score is None:
        return None
    return {
        "event_id": str(_first(event.get("id"), comp.get("id"))),
        "competition_id": str(_first(comp.get("id"), event.get("id"))),
        "date": str(_first(event.get("date"), comp.get("date"))),
        "home": str(_first((home.get("team") or {}).get("displayName"))),
        "away": str(_first((away.get("team") or {}).get("displayName"))),
        "home_score": home_score,
        "away_score": away_score,
    }


def parse_scoreboard(payload: dict) -> list[dict[str, Any]]:
    """Completed games from one ESPN scoreboard payload (all other states dropped)."""
    out: list[dict[str, Any]] = []
    for event in payload.get("events") or ():
        comp = _completed(event)
        if comp is None:
            continue
        row = _scoreboard_row(event, comp)
        if row is not None:
            out.append(row)
    return out


def fetch_results(sport: str, league: str, date: str) -> list[dict[str, Any]]:
    """Fetch settled games for ``date`` (``YYYYMMDD`` or ``YYYY-MM-DD``).

    Returns ``[]`` when the day has no completed game; raises on transport or
    payload errors so a network failure is never mistaken for "no games".
    """
    day = date.replace("-", "")
    payload = _get_json(SCOREBOARD.format(sport=sport, league=league) + f"?dates={day}")
    return parse_scoreboard(payload)


def _decimal(market: dict) -> float | None:
    value = market.get("decimal") or market.get("value")
    return float(value) if value else None


def parse_moneyline(payload: dict, side: str) -> dict[str, Any]:
    """Decimal open (bet-time) and close price for ``side`` (``home``/``away``)."""
    team = payload.get(f"{side}TeamOdds") or {}
    bet_time = _decimal((team.get("open") or {}).get("moneyLine") or {})
    closing = _decimal((team.get("close") or {}).get("moneyLine") or {})
    if bet_time is None or closing is None:
        return {}
    return {
        "odds": bet_time,
        "closing_odds": closing,
        "side": side,
        "provider": str((payload.get("provider") or {}).get("name") or ""),
    }


def fetch_moneyline(
    sport: str,
    league: str,
    event_id: str,
    competition_id: str,
    side: str = "home",
) -> dict[str, Any]:
    """Fetch one event's open/close moneyline from the default ESPN provider."""
    payload = _get_json(
        ODDS.format(
            sport=sport, league=league, event=event_id, comp=competition_id, provider=PROVIDER
        )
    )
    item = (payload[0] if payload else {}) if isinstance(payload, list) else payload
    return parse_moneyline(item, side)


def derive_won(home_score: int, away_score: int, side: str) -> bool | None:
    """Moneyline win for ``side``. ``None`` on a tie: a push is not a win."""
    if int(home_score) == int(away_score):
        return None
    want_home = str(side).strip().lower() == "home"
    return (int(home_score) > int(away_score)) if want_home else (int(away_score) > int(home_score))
