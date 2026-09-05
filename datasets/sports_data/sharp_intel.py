"""Sharp money intelligence — steam moves, RLM, bet/money divergence, line watch.

Professional bettors read the market through four lenses, and this module
approximates all of them from free sources (The Odds API via
``PRY_ODDS_API_KEY`` with an ESPN fallback for the slate, plus an optional
configured public-betting-percentage feed via ``PRY_SHARP_BET_FEED``):

1. **Steam moves** — a line that moved 1+ point across 3+ books inside a
   short window. Steam is the market's loudest sharp signal: when many
   independent books move simultaneously, one big bettor (or a syndicate)
   is moving them. We poll the live multi-book comparison on every call,
   keep a bounded in-memory snapshot history per sport (same best-effort
   design as :mod:`datasets.sports_data.line_movement`), and flag moves
   where enough books shifted in the same direction within the lookback.
2. **Reverse line movement (RLM)** — the line moves *toward* the side the
   public is NOT on. If 70% of tickets are on the Lakers but the line
   moves toward the Lakers' opponent, sharps are on the opponent.
3. **Bet % vs money % divergence** — tickets count bets, money counts
   dollars. When 70% of bets but only 45% of money is on team A, big
   bettors are on team B. Divergence = money_pct - bet_pct.
4. **Line watch** — current vs opening line per book, with the best
   available number and a value indicator against market consensus.

[REVIEW] Feasibility flag: there is **no stable no-auth public API** for
per-event public betting percentages (tickets vs money) as of 2026 — Action
Network requires auth and Covers renders client-side. The bet-percentage
paths (RLM, divergence) therefore depend on ``PRY_SHARP_BET_FEED``: a JSON
endpoint returning ``[{event, home_bet_pct, away_bet_pct, home_money_pct,
away_money_pct}, ...]`` (alternate key spellings tolerated, ``{sport}``
placeholder supported). When the feed is not configured or returns nothing
parseable, those functions return ``[]`` — they never fabricate
percentages. Steam moves and line watch work from odds alone.

Contract
--------
All public functions are async, never raise, and return ``[]`` / ``{}`` on
failure (unknown sport, network failure, unconfigured feed).

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
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Sources ────────────────────────────────────────────────────────────
_ODDS_API_BASE = "https://api.the-odds-api.com/v4"
_ODDS_API_KEY_ENV = "PRY_ODDS_API_KEY"
_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
# Optional per-sport public betting-percentage feed (see module docstring).
_BET_FEED_ENV = "PRY_SHARP_BET_FEED"

_TIMEOUT = httpx.Timeout(10.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

# ESPN path segments per sport slug (fallback slate source).
_ESPN_PATHS: dict[str, str] = {
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

# ── Steam thresholds ───────────────────────────────────────────────────
# Minimum books that must move the same side inside the window.
_STEAM_MIN_BOOKS = 3
# Books required for "high" confidence.
_STEAM_HIGH_CONFIDENCE_BOOKS = 5
# Minimum absolute line change (decimal-odds points) to count as a move.
_STEAM_MIN_MOVE = 0.01

# ── RLM / divergence thresholds ────────────────────────────────────────
# Minimum |money_pct - bet_pct| (percentage points) to flag divergence.
_DIVERGENCE_MIN = 10.0
# Minimum line move (decimal odds ratio) for an RLM signal to fire.
_RLM_MIN_MOVE_PCT = 0.02

# ── In-memory snapshot history (best-effort, no persistence) ───────────
_MAX_SNAPSHOTS_PER_SPORT = 60
_PRUNE_AFTER_MINUTES = 180

# sport -> list[snapshot]; snapshot = {"at": iso, "events": {event_id: {book: {outcome: odds}}}}
_history: dict[str, list[dict[str, Any]]] = {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_at(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):  # pragma: no cover - internal data is ours
        return datetime.now(UTC)


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


# ── HTTP helpers (never raise) ─────────────────────────────────────────
async def _fetch_json(url: str, params: dict[str, str] | None = None) -> Any:
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
async def _odds_api_events(sport: str) -> list[dict[str, Any]]:
    """Fetch The Odds API event list with h2h + spreads for one sport."""
    api_key = os.environ.get(_ODDS_API_KEY_ENV, "").strip()
    if not api_key:
        return []
    payload = await _fetch_json(
        f"{_ODDS_API_BASE}/sports/{sport}/odds",
        params={
            "apiKey": api_key,
            "regions": "us,eu",
            "markets": "h2h,spreads",
            "oddsFormat": "decimal",
        },
    )
    return payload if isinstance(payload, list) else []


def _espn_events(sport: str) -> list[dict[str, Any]]:
    """ESPN scoreboard fallback: build minimal event records (sync helper)."""
    path = _ESPN_PATHS.get(sport)
    if not path:
        return []
    import asyncio

    async def _one() -> Any:
        return await _fetch_json(f"{_ESPN_BASE}/{path}/scoreboard")

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


async def _load_slate(sport: str) -> list[dict[str, Any]]:
    """Fetch the event slate for one sport (The Odds API, ESPN fallback)."""
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await _odds_api_events(normalized)
    if events:
        return events
    return _espn_events(normalized)


# ── Snapshot history ───────────────────────────────────────────────────
def _record_snapshot(sport: str, events: list[dict[str, Any]]) -> None:
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
                    point = _to_float(outcome.get("point"))
                    price = _to_float(outcome.get("price"))
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
    history = _history.setdefault(sport, [])
    history.append({"at": _now_iso(), "events": parsed})
    _prune_history(sport)


def _prune_history(sport: str) -> None:
    cutoff = datetime.now(UTC) - timedelta(minutes=_PRUNE_AFTER_MINUTES)
    retained = [
        snapshot for snapshot in _history.get(sport, []) if _parse_at(snapshot.get("at")) >= cutoff
    ]
    if retained:
        _history[sport] = retained[-_MAX_SNAPSHOTS_PER_SPORT:]
    else:
        _history.pop(sport, None)


def _event_label(event: dict[str, Any]) -> str:
    home = str(event.get("home_team") or "")
    away = str(event.get("away_team") or "")
    if home and away:
        return f"{away} @ {home}"
    return str(event.get("id") or "unknown event")


# ── Steam moves ────────────────────────────────────────────────────────
def _compute_steam(sport: str, lookback_minutes: int) -> list[dict[str, Any]]:
    """Detect steam moves from the recorded snapshot history."""
    try:
        window = max(1, int(lookback_minutes))
    except (TypeError, ValueError):
        window = 60
    cutoff = datetime.now(UTC) - timedelta(minutes=window)
    snapshots = [
        snapshot for snapshot in _history.get(sport, []) if _parse_at(snapshot.get("at")) >= cutoff
    ]
    if len(snapshots) < 2:
        return []
    first, last = snapshots[0], snapshots[-1]
    first_events = first.get("events") or {}
    last_events = last.get("events") or {}
    moves: list[dict[str, Any]] = []
    for event_id, last_books in last_events.items():
        first_books = first_events.get(event_id)
        if not isinstance(first_books, dict):
            continue
        # Collect per-outcome movement across books.
        outcomes: set[str] = set()
        for prices in last_books.values():
            if isinstance(prices, dict):
                outcomes.update(prices)
        for outcome in sorted(outcomes):
            books_moved: list[str] = []
            directions: list[float] = []
            for book_key, last_prices in last_books.items():
                first_prices = first_books.get(book_key)
                if not isinstance(first_prices, dict):
                    continue
                old = _to_float(first_prices.get(outcome))
                new = _to_float(last_prices.get(outcome))
                if old is None or new is None or old == new:
                    continue
                if abs(new - old) < _STEAM_MIN_MOVE:
                    continue
                books_moved.append(book_key)
                directions.append(new - old)
            if len(books_moved) < _STEAM_MIN_BOOKS:
                continue
            # All moved books must agree on direction for steam.
            if any((d > 0) != (directions[0] > 0) for d in directions):
                continue
            magnitude = round(max(abs(d) for d in directions), 4)
            avg_old = sum(_to_float(first_books[b].get(outcome)) or 0.0 for b in books_moved) / len(
                books_moved
            )
            avg_new = sum(_to_float(last_books[b].get(outcome)) or 0.0 for b in books_moved) / len(
                books_moved
            )
            confidence = "high" if len(books_moved) >= _STEAM_HIGH_CONFIDENCE_BOOKS else "medium"
            moves.append(
                {
                    "event_id": event_id,
                    "event": _event_label(last_events.get(event_id, {})),
                    "market": "h2h",
                    "outcome": outcome,
                    "old_line": round(avg_old, 4),
                    "new_line": round(avg_new, 4),
                    "books_moved": sorted(books_moved),
                    "move_direction": "up" if directions[0] > 0 else "down",
                    "move_magnitude": magnitude,
                    "timestamp": str(last.get("at") or ""),
                    "confidence": confidence,
                }
            )
    moves.sort(key=lambda item: -float(item.get("move_magnitude") or 0.0))
    return moves


# ── Betting-percentage feed ────────────────────────────────────────────
_BET_KEYS = {
    "home_bet": ("home_bet_pct", "homeBetPct", "home_tickets_pct", "home_ticket_pct"),
    "away_bet": ("away_bet_pct", "awayBetPct", "away_tickets_pct", "away_ticket_pct"),
    "home_money": ("home_money_pct", "homeMoneyPct", "home_money_percent"),
    "away_money": ("away_money_pct", "awayMoneyPct", "away_money_percent"),
}


def _pick_pct(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _to_float(payload.get(key))
        if value is not None and 0.0 <= value <= 100.0:
            return value
    return None


async def _load_bet_percentages(sport: str) -> dict[str, dict[str, float]]:
    """Load per-event bet/money percentages from the configured feed.

    Returns ``{event_label_lower: {home_bet, away_bet, home_money, away_money}}``
    or ``{}`` when the feed is unconfigured/unparseable. Never fabricates.
    """
    feed_url = os.environ.get(_BET_FEED_ENV, "").strip()
    if not feed_url:
        return []
    url = feed_url.replace("{sport}", sport)
    payload = await _fetch_json(url)
    rows: list[Any] = payload if isinstance(payload, list) else (payload or {}).get("events", [])
    result: dict[str, dict[str, float]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        event = str(row.get("event") or row.get("matchup") or "").strip()
        if not event:
            continue
        pcts: dict[str, float] = {}
        for slot, keys in _BET_KEYS.items():
            value = _pick_pct(row, keys)
            if value is not None:
                pcts[slot] = value
        if pcts:
            result[event.lower()] = pcts
    return result


# ── RLM ────────────────────────────────────────────────────────────────
async def get_reverse_line_movement(sport: str = "nba") -> list[dict[str, Any]]:
    """Find reverse line movement: line moved toward the less-bet side.

    Args:
        sport: Sport slug (nba, nfl, mlb, nhl, ...).

    Returns:
        List of RLM dicts (see module docstring) or ``[]`` on failure.
        Requires the ``PRY_SHARP_BET_FEED`` betting-percentage feed; without
        it, public percentages are unknown and no RLM signal is fabricated.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await _load_slate(normalized)
    if not events:
        return []
    _record_snapshot(normalized, events)
    bet_pcts = await _load_bet_percentages(normalized)
    if not bet_pcts:
        return []
    history = _history.get(normalized) or []
    if len(history) < 2:
        return []
    first_events = history[0].get("events") or {}
    last_events = history[-1].get("events") or {}
    results: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "")
        label = _event_label(event)
        pcts = bet_pcts.get(label.lower())
        if not pcts or not event_id:
            continue
        first_books = first_events.get(event_id)
        last_books = last_events.get(event_id)
        if not isinstance(first_books, dict) or not isinstance(last_books, dict):
            continue
        for side, bet_key, _money_key in (
            ("home", "home_bet", "home_money"),
            ("away", "away_bet", "away_money"),
        ):
            bet_pct = pcts.get(bet_key)
            if bet_pct is None:
                continue
            # Movement proxy: average h2h price of the side's outcome across
            # books present in both snapshots.
            deltas: list[float] = []
            for book_key, last_prices in last_books.items():
                first_prices = first_books.get(book_key)
                if not isinstance(first_prices, dict):
                    continue
                # h2h outcomes are keyed "Team|h2h"; match by team prefix.
                team = str(event.get("home_team") if side == "home" else event.get("away_team"))
                matches_last = [v for k, v in last_prices.items() if k.startswith(f"{team}|h2h")]
                matches_first = [v for k, v in first_prices.items() if k.startswith(f"{team}|h2h")]
                if not matches_last or not matches_first:
                    continue
                delta = matches_last[0] - matches_first[0]
                if abs(delta) >= _RLM_MIN_MOVE_PCT * matches_first[0]:
                    deltas.append(delta)
            if not deltas:
                continue
            moved = sum(deltas) / len(deltas)
            # RLM: line moved toward the side with LESS public betting.
            # Odds moving down (shorter) = market backing that side.
            less_bet_side = bet_pct < 50.0
            moved_toward = moved < 0 if less_bet_side else moved > 0
            rlm_signal = moved_toward and bet_pct <= 40.0
            divergence = abs(50.0 - bet_pct)
            strength = (
                "strong"
                if divergence >= 25 and rlm_signal
                else ("moderate" if rlm_signal else "weak")
            )
            results.append(
                {
                    "event": label,
                    "event_id": event_id,
                    "sport": normalized,
                    "side": side,
                    "public_bet_pct": round(bet_pct, 1),
                    "line_movement": "toward" if moved_toward else "away",
                    "line_move_pct": round(moved / max(matches_first[0], 1.0) * 100.0, 2),
                    "rlm_signal": rlm_signal,
                    "strength": strength,
                }
            )
    return [item for item in results if item.get("rlm_signal")]


# ── Bet vs money divergence ────────────────────────────────────────────
async def get_bet_vs_money_divergence(sport: str = "nba") -> list[dict[str, Any]]:
    """Find events where bet % and money % diverge significantly.

    The sharp side is the one with more money but fewer tickets.

    Returns:
        List of divergence dicts or ``[]`` (requires ``PRY_SHARP_BET_FEED``).
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await _load_slate(normalized)
    if not events:
        return []
    bet_pcts = await _load_bet_percentages(normalized)
    if not bet_pcts:
        return []
    results: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        label = _event_label(event)
        pcts = bet_pcts.get(label.lower())
        if not pcts:
            continue
        for side, bet_key, money_key in (
            ("home", "home_bet", "home_money"),
            ("away", "away_bet", "away_money"),
        ):
            bet_pct = pcts.get(bet_key)
            money_pct = pcts.get(money_key)
            if bet_pct is None or money_pct is None:
                continue
            divergence = round(money_pct - bet_pct, 1)
            if abs(divergence) < _DIVERGENCE_MIN:
                continue
            # Sharp side: more money, fewer bets.
            sharp_side = side if divergence > 0 else None
            confidence = (
                "high" if abs(divergence) >= 25 else ("medium" if abs(divergence) >= 15 else "low")
            )
            results.append(
                {
                    "event": label,
                    "event_id": str(event.get("id") or ""),
                    "sport": normalized,
                    "side": side,
                    "bet_pct": round(bet_pct, 1),
                    "money_pct": round(money_pct, 1),
                    "divergence": divergence,
                    "sharp_side": sharp_side,
                    "confidence": confidence,
                }
            )
    results.sort(key=lambda item: -abs(float(item.get("divergence") or 0)))
    return results


# ── Line watch ─────────────────────────────────────────────────────────
async def get_line_watch(sport: str = "nba") -> list[dict[str, Any]]:
    """Lines worth watching: current vs opening, best book, value indicator.

    Returns:
        List of line-watch dicts (see module docstring) or ``[]`` on failure.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await _load_slate(normalized)
    if not events:
        return []
    _record_snapshot(normalized, events)
    history = _history.get(normalized) or []
    first_events = history[0].get("events") if history else {}
    last_events = history[-1].get("events") if history else {}
    results: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        last_books = (last_events or {}).get(event_id)
        if not isinstance(last_books, dict) or not last_books:
            continue
        first_books = (first_events or {}).get(event_id) or {}
        # Consensus = mean price per outcome across books.
        consensus: dict[str, float] = {}
        counts: dict[str, int] = {}
        for prices in last_books.values():
            if not isinstance(prices, dict):
                continue
            for outcome, price in prices.items():
                value = _to_float(price)
                if value is None:
                    continue
                consensus[outcome] = consensus.get(outcome, 0.0) + value
                counts[outcome] = counts.get(outcome, 0) + 1
        for outcome in list(consensus):
            if counts.get(outcome):
                consensus[outcome] = consensus[outcome] / counts[outcome]
        best_book: str | None = None
        best_price: float | None = None
        movement_total = 0.0
        movement_count = 0
        for book_key, prices in last_books.items():
            if not isinstance(prices, dict):
                continue
            for outcome, price in prices.items():
                value = _to_float(price)
                if value is None:
                    continue
                # "Best" line for a bettor = highest decimal price on any
                # outcome (better payout than consensus).
                if best_price is None or value > best_price:
                    best_price = value
                    best_book = book_key
                first_prices = first_books.get(book_key)
                if isinstance(first_prices, dict):
                    old = _to_float(first_prices.get(outcome))
                    if old is not None and old != value:
                        movement_total += value - old
                        movement_count += 1
        if best_book is None:
            continue
        avg_movement = round(movement_total / movement_count, 4) if movement_count else 0.0
        # Value indicator: best price vs consensus on the same outcome.
        outcome_of_best = next(
            (o for o, p in last_books.get(best_book, {}).items() if _to_float(p) == best_price),
            None,
        )
        value_indicator = "good_line"
        if outcome_of_best and outcome_of_best in consensus:
            edge = best_price - consensus[outcome_of_best]
            value_indicator = (
                "good_line" if edge > 0.01 else ("bad_line" if edge < -0.01 else "fair_line")
            )
        results.append(
            {
                "event": _event_label(event),
                "event_id": event_id,
                "sport": normalized,
                "market": "h2h",
                "current_line": round(best_price, 4) if best_price is not None else None,
                "opening_line": round(
                    (
                        _to_float((first_books.get(best_book) or {}).get(outcome_of_best))
                        or best_price
                    ),
                    4,
                )
                if best_price is not None
                else None,
                "movement": avg_movement,
                "best_line": {
                    "book": best_book,
                    "price": round(best_price, 4) if best_price else None,
                },
                "value_indicator": value_indicator,
            }
        )
    return results


# ── Steam moves (public API) ───────────────────────────────────────────
async def get_steam_moves(sport: str = "nba", lookback_minutes: int = 60) -> list[dict[str, Any]]:
    """Detect steam moves: 1+ point shifts across 3+ books in a short window.

    Args:
        sport: Sport slug (nba, nfl, mlb, nhl, ...).
        lookback_minutes: Window for comparing the earliest vs latest
            recorded snapshot (in-memory history; poll repeatedly for
            meaningful windows).

    Returns:
        List of steam-move dicts (see module docstring) or ``[]`` on
        failure. ``confidence`` is ``high`` when 5+ books moved
        simultaneously, ``medium`` otherwise. Never raises.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    events = await _load_slate(normalized)
    if not events:
        return []
    _record_snapshot(normalized, events)
    return _compute_steam(normalized, lookback_minutes)


# ── Sharp report ───────────────────────────────────────────────────────
async def get_sharp_report(sport: str = "nba") -> dict[str, Any]:
    """Full sharp money report: steam + RLM + divergence + line watch.

    Returns:
        Report dict with counts, top signals, and overall sharp indicators
        (games with the most aligned sharp signals), or ``{}`` on failure.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return {}
    steam = await get_steam_moves(normalized)
    rlm = await get_reverse_line_movement(normalized)
    divergence = await get_bet_vs_money_divergence(normalized)
    watch = await get_line_watch(normalized)
    if not (steam or rlm or divergence or watch):
        return {}
    # Overall sharp indicators: events touched by the most signal types.
    tally: dict[str, dict[str, Any]] = {}
    for item in steam:
        entry = tally.setdefault(
            str(item.get("event") or ""), {"signals": set(), "event": item.get("event")}
        )
        entry["signals"].add("steam")
    for item in rlm:
        entry = tally.setdefault(
            str(item.get("event") or ""), {"signals": set(), "event": item.get("event")}
        )
        entry["signals"].add("rlm")
    for item in divergence:
        if item.get("sharp_side"):
            entry = tally.setdefault(
                str(item.get("event") or ""), {"signals": set(), "event": item.get("event")}
            )
            entry["signals"].add("divergence")
    overall = sorted(
        (
            {"event": entry["event"], "signals": sorted(entry["signals"])}
            for entry in tally.values()
            if len(entry["signals"]) >= 1
        ),
        key=lambda item: -len(item["signals"]),
    )
    return {
        "sport": normalized,
        "generated_at": _now_iso(),
        "steam_moves_count": len(steam),
        "rlm_signals": len(rlm),
        "top_divergences": divergence[:5],
        "line_watch_items": len(watch),
        "steam_moves": steam[:10],
        "rlm": rlm[:10],
        "overall_sharp_indicators": overall[:10],
    }


# ── Consensus sharp picks ──────────────────────────────────────────────
async def get_consensus_sharp_picks(sport: str = "nba") -> list[dict[str, Any]]:
    """Games where multiple sharp indicators align on the same side.

    Returns:
        List of consensus dicts: event, indicators fired, sharp_pick side,
        confidence_level, recommended_bet. ``[]`` on failure.
    """
    normalized = str(sport or "").strip().lower()
    if not normalized:
        return []
    steam = await get_steam_moves(normalized)
    rlm = await get_reverse_line_movement(normalized)
    divergence = await get_bet_vs_money_divergence(normalized)
    picks: dict[str, dict[str, Any]] = {}

    def _entry(event: str, event_id: str) -> dict[str, Any]:
        return picks.setdefault(
            event,
            {"event": event, "event_id": event_id, "indicators": [], "sides": []},
        )

    for item in steam:
        entry = _entry(str(item.get("event") or ""), str(item.get("event_id") or ""))
        entry["indicators"].append("steam")
        entry["sides"].append(str(item.get("outcome") or ""))
    for item in rlm:
        if not item.get("rlm_signal"):
            continue
        entry = _entry(str(item.get("event") or ""), str(item.get("event_id") or ""))
        entry["indicators"].append("rlm")
        entry["sides"].append(str(item.get("side") or ""))
    for item in divergence:
        sharp_side = item.get("sharp_side")
        if not sharp_side:
            continue
        entry = _entry(str(item.get("event") or ""), str(item.get("event_id") or ""))
        entry["indicators"].append("divergence")
        entry["sides"].append(str(sharp_side))

    results: list[dict[str, Any]] = []
    for event, entry in picks.items():
        indicators = entry["indicators"]
        if len(indicators) < 2:
            continue
        sides = [side for side in entry["sides"] if side]
        aligned = len(set(sides)) == 1 and len(sides) == len(indicators)
        confidence_level = (
            "high" if (len(indicators) >= 3 and aligned) else ("medium" if aligned else "low")
        )
        results.append(
            {
                "event": event,
                "event_id": entry["event_id"],
                "sport": normalized,
                "indicators": indicators,
                "sharp_pick": sides[0] if aligned and sides else None,
                "confidence_level": confidence_level,
                "recommended_bet": (
                    f"{'Side: ' + str(sides[0]) if aligned and sides else 'Watch only'} "
                    f"({len(indicators)} sharp indicators)"
                ),
            }
        )
    results.sort(key=lambda item: -len(item.get("indicators") or []))
    return results
