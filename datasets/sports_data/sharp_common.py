"""Shared transport, constants, and snapshot store for sharp money modules.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Sources ────────────────────────────────────────────────────────────
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_KEY_ENV = "PRY_ODDS_API_KEY"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
# Optional per-sport public betting-percentage feed.
BET_FEED_ENV = "PRY_SHARP_BET_FEED"

_TIMEOUT = httpx.Timeout(10.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

# ESPN path segments per sport slug (fallback slate source).
ESPN_PATHS: dict[str, str] = {
    "nba": "basketball/nba",
    "nfl": "football/nfl",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
    "wnba": "basketball/wnba",
    "ncaab": "basketball/mens-college-basketball",
    "ncaaf": "football/college-football",
    "epl": "soccer/eng.1",
    "mls": "soccer/usa.1",
}

# ── In-memory snapshot history (best-effort, no persistence) ───────────
MAX_SNAPSHOTS_PER_SPORT = 60
PRUNE_AFTER_MINUTES = 180

# sport -> list[snapshot]; snapshot = {"at": iso, "events": {event_id: {book: {outcome: odds}}}}
history: dict[str, list[dict[str, Any]]] = {}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_at(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):  # pragma: no cover - internal data is ours
        return datetime.now(UTC)


def to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


# ── HTTP helpers (never raise) ─────────────────────────────────────────
async def fetch_json(url: str, params: dict[str, str] | None = None) -> Any:
    """GET a JSON payload; return ``None`` on any failure."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, OSError, ValueError):
        logger.debug("sharp_intel_fetch_failed", extra={"url": url})
        return None


# ── Slate fetching ─────────────────────────────────────────────────────
async def odds_api_events(sport: str) -> list[dict[str, Any]]:
    """Fetch The Odds API event list with h2h + spreads for one sport."""
    api_key = os.environ.get(ODDS_API_KEY_ENV, "").strip()
    if not api_key:
        return []
    payload = await fetch_json(
        f"{ODDS_API_BASE}/sports/{sport}/odds",
        params={
            "apiKey": api_key,
            "regions": "us,eu",
            "markets": "h2h,spreads",
            "oddsFormat": "decimal",
        },
    )
    return payload if isinstance(payload, list) else []


def espn_events(sport: str) -> list[dict[str, Any]]:
    """ESPN scoreboard fallback: build minimal event records (sync helper)."""
    path = ESPN_PATHS.get(sport)
    if not path:
        return []
    import asyncio

    async def _one() -> Any:
        return await fetch_json(f"{ESPN_BASE}/{path}/scoreboard")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:  # pragma: no cover - called from async context
        return []
    try:
        payload = asyncio.run(_one())
    except (RuntimeError, OSError):
        return []
    events: list[dict[str, Any]] = []
    for event in (payload or {}).get("events", []) if isinstance(payload, dict) else []:
        if not isinstance(event, dict):
            continue
        competitions = event.get("competitions") or []
        if not competitions or not isinstance(competitions[0], dict):
            continue
        competitors = competitions[0].get("competitors") or []
        if len(competitors) < 2:
            continue
        away = competitors[0] if competitors[0].get("homeAway") == "away" else competitors[1]
        home = competitors[1] if away is competitors[0] else competitors[0]
        events.append(
            {
                "id": str(event.get("id") or ""),
                "sport_key": sport,
                "commence_time": str(event.get("date") or ""),
                "home_team": str((home.get("team") or {}).get("displayName") or ""),
                "away_team": str((away.get("team") or {}).get("displayName") or ""),
                "bookmakers": [],
            }
        )
    return events


async def load_slate(sport: str) -> list[dict[str, Any]]:
    """Fetch the event slate for one sport (The Odds API, ESPN fallback)."""
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await odds_api_events(normalized)
    if events:
        return events
    return espn_events(normalized)


# ── Snapshot history ───────────────────────────────────────────────────
def record_snapshot(sport: str, events: list[dict[str, Any]]) -> None:
    """Record one bounded snapshot of the slate into in-memory history."""
    parsed: dict[str, dict[str, dict[str, float]]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        books: dict[str, dict[str, float]] = {}
        for book in event.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            book_key = str(book.get("key") or book.get("title") or "").strip().lower()
            if not book_key:
                continue
            prices: dict[str, float] = {}
            for market in book.get("markets") or []:
                if not isinstance(market, dict):
                    continue
                market_key = str(market.get("key") or "")
                if market_key not in ("h2h", "spreads"):
                    continue
                for outcome in market.get("outcomes") or []:
                    if not isinstance(outcome, dict):
                        continue
                    name = str(outcome.get("name") or "")
                    point = to_float(outcome.get("point"))
                    price = to_float(outcome.get("price"))
                    if not name or price is None or price <= 1.0:
                        continue
                    # Spreads carry a point; key the outcome by name+point so
                    # a spread move shows up as a key change, not a price blur.
                    label = f"{name}|{market_key}" + (f"|{point}" if point is not None else "")
                    prices[label] = price
            if prices:
                books[book_key] = prices
        if books:
            parsed[event_id] = books
    if not parsed:
        return
    snapshots = history.setdefault(sport, [])
    snapshots.append({"at": now_iso(), "events": parsed})
    prune_history(sport)


def prune_history(sport: str) -> None:
    cutoff = datetime.now(UTC) - timedelta(minutes=PRUNE_AFTER_MINUTES)
    retained = [
        snapshot for snapshot in history.get(sport, []) if parse_at(snapshot.get("at")) >= cutoff
    ]
    if retained:
        history[sport] = retained[-MAX_SNAPSHOTS_PER_SPORT:]
    else:
        history.pop(sport, None)


def event_label(event: dict[str, Any]) -> str:
    home = str(event.get("home_team") or "")
    away = str(event.get("away_team") or "")
    if home and away:
        return f"{away} @ {home}"
    return str(event.get("id") or "unknown event")


# ── Betting-percentage feed ────────────────────────────────────────────
BET_KEYS = {
    "home_bet": ("home_bet_pct", "homeBetPct", "home_tickets_pct", "home_ticket_pct"),
    "away_bet": ("away_bet_pct", "awayBetPct", "away_tickets_pct", "away_ticket_pct"),
    "home_money": ("home_money_pct", "homeMoneyPct", "home_money_percent"),
    "away_money": ("away_money_pct", "awayMoneyPct", "away_money_percent"),
}


def pick_pct(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = to_float(payload.get(key))
        if value is not None and 0.0 <= value <= 100.0:
            return value
    return None


async def load_bet_percentages(sport: str) -> dict[str, dict[str, float]]:
    """Load per-event bet/money percentages from the configured feed.

    Returns ``{event_label_lower: {home_bet, away_bet, home_money, away_money}}``
    or ``{}`` when the feed is unconfigured/unparseable. Never fabricates.
    """
    feed_url = os.environ.get(BET_FEED_ENV, "").strip()
    if not feed_url:
        return {}
    url = feed_url.replace("{sport}", sport)
    payload = await fetch_json(url)
    rows: list[Any] = payload if isinstance(payload, list) else (payload or {}).get("events", [])
    result: dict[str, dict[str, float]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        event = str(row.get("event") or row.get("matchup") or "").strip()
        if not event:
            continue
        pcts: dict[str, float] = {}
        for slot, keys in BET_KEYS.items():
            value = pick_pct(row, keys)
            if value is not None:
                pcts[slot] = value
        if pcts:
            result[event.lower()] = pcts
    return result
