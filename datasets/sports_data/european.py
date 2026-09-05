"""European / globally-reachable sportsbook odds fetchers for Pry.

Covers the books that are reachable without a US geo-IP, prioritizing the
high-value sharp/consensus books:

* **Pinnacle** — the sharpest book. Uses the semi-public guest JSON API
  (``guest.api.pinnacle.com/v1``: ``/leagues``, ``/fixtures``, ``/odds``),
  no auth, decimal odds; the sharp line for CLV / no-vig consensus.
* **Marathonbet** — server-rendered coupon pages (decimal odds rows).
* **1xBet** — internal ``LineFeed`` JSON endpoint (gzip/base64 payload).
* **Betfair** — public read-only Exchange endpoint
  (``/www/sports/exchange/readonly/v1/bymarket``) plus market-ID discovery
  from the exchange pages. No login required.
* **Betway, 10Bet, SBOBet, Dafabet, 12Bet, W88** — best-effort embedded
  state / HTML row parsing; several are JS-heavy or hard-geo-blocked, and
  plain HTTP often returns no odds — that is flagged honestly.

Transport: Pry's own httpx + stealth headers, with a Webshare proxy retry
(``WEBSHARE_PROXY_LIST``) when a direct request looks geo-blocked (shared
with :mod:`sports_data.offshore`).

Contract
--------
* :func:`fetch_european_odds` aggregates every per-book fetcher and never
  raises — it returns ``[]`` on any failure. One dead book never affects
  the others.
* Every record follows the canonical odds schema from
  :mod:`sports_data.odds` and is tagged ``source="european"``.

Free-API terms: Pinnacle guest API and the Betfair read-only endpoint are
undocumented public feeds; Marathonbet/1xBet pages are consumer pages —
scrape politely, expect layout drift and blocks.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import base64
import gzip
import json
import logging
import re
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

import datasets.sports_data.offshore as offshore
import datasets.sports_data.sources as sources
from datasets.sports_data.offshore import (
    _fetch_json_geo,
    _fetch_text_geo,
    _parse_decimal_rows,
    _parse_embedded_state,
)
from datasets.sports_data.sources import _as_text, _to_float

# ── Data-driven registry loader ─────────────────────────────────────────
# Static book metadata + sport→path maps live as plain JSON (data, not
# code) under ``data/european.json``; this module loads them at import.
_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(name: str) -> Any:
    with (_DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


# Guarded import: sports_data.odds is extended by a parallel agent; this
# module is imported by the package during init, so degrade gracefully if
# the sibling is momentarily unavailable (parallel build safety).
try:
    from datasets.sports_data.odds import (
        _SPORTS,
        _american_to_decimal,
        _event_label,
        _resolve_sports,
    )
except ImportError:  # pragma: no cover - parallel build guard
    _american_to_decimal = None  # type: ignore[assignment]
    _event_label = None  # type: ignore[assignment]
    _resolve_sports = None  # type: ignore[assignment]
    _SPORTS = {}  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Book registry ───────────────────────────────────────────────────────
# Canonical book slug -> {name (display), base_url, kind, confidence, notes}.
# kind: "json" (internal JSON endpoint), "html" (server-rendered coupon),
# "exchange" (Betfair read-only API), "embedded" (generic best-effort).
# The registry itself is data-driven (JSON).
_EUROPEAN_DATA: dict[str, Any] = _load_json("european.json")
EUROPEAN_BOOKS: dict[str, dict[str, Any]] = _EUROPEAN_DATA["EUROPEAN_BOOKS"]

# Aggregate order (also used for book_status iteration).
EUROPEAN_BOOK_ORDER: tuple[str, ...] = tuple(_EUROPEAN_DATA["EUROPEAN_BOOK_ORDER"])

# Canonical sport slug -> (book path slug, league path slug or None) used
# by the generic (embedded/html) books. Data-driven.
_EUROPEAN_SPORTS: dict[str, tuple[str, str | None]] = {
    k: (v[0], v[1]) for k, v in _EUROPEAN_DATA["_EUROPEAN_SPORTS"].items()
}

# ── Live availability tracking ──────────────────────────────────────────
# Guarded reuse of the sibling BOOKS registry (sports_data.books — owned by
# another agent in this batch). When present, book_status() annotates each
# entry with the sibling's geo/method metadata; fetch logic stays fully
# independent, so this degrades to no-op if the sibling module is missing.
try:
    import datasets.sports_data.books as _sibling_books

    _SIBLING_BOOKS: dict[str, dict[str, Any]] | None = getattr(_sibling_books, "BOOKS", None)
except ImportError:  # pragma: no cover - sibling module may not exist yet
    _SIBLING_BOOKS = None

# My slugs that don't match the sibling's book ids / display names directly.
_SIBLING_ALIASES: dict[str, str] = {"betway": "betway-uk"}


def _sibling_entry(book: str) -> dict[str, Any] | None:
    """Sibling registry entry for a book slug (by id, display name, alias)."""
    if not _SIBLING_BOOKS:
        return None
    direct = _SIBLING_BOOKS.get(book) or _SIBLING_BOOKS.get(_SIBLING_ALIASES.get(book, ""))
    if isinstance(direct, dict):
        return direct
    norm = "".join(ch for ch in book.lower() if ch.isalnum())
    for entry in _SIBLING_BOOKS.values():
        if not isinstance(entry, dict):
            continue
        name_key = "".join(ch for ch in str(entry.get("name") or "").lower() if ch.isalnum())
        if name_key == norm:
            return entry
    return None


def _status_entry(book: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Registry entry + live availability + optional sibling annotation."""
    result = {"name": book, **entry, "availability": dict(_BOOK_HEALTH.get(book, {}))}
    sibling = _sibling_entry(book)
    if sibling is not None:
        result["sibling"] = {
            "book_id": sibling.get("id"),
            "category": sibling.get("category"),
            "method": sibling.get("method"),
            "geo_required": bool(sibling.get("geo_required")),
        }
    return result


_BOOK_HEALTH: dict[str, dict[str, Any]] = {
    book: {
        "reachable": True,
        "blocked": False,
        "last_checked": None,
        "latency_ms": None,
        "error": None,
    }
    for book in EUROPEAN_BOOK_ORDER
}


def _mark_book(
    book: str,
    *,
    ok: bool,
    blocked: bool = False,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Record the outcome of the last fetch attempt for one book."""
    health = _BOOK_HEALTH.setdefault(
        book,
        {
            "reachable": True,
            "blocked": False,
            "last_checked": None,
            "latency_ms": None,
            "error": None,
        },
    )
    health["reachable"] = ok and not blocked
    health["blocked"] = bool(blocked)
    health["last_checked"] = datetime.now(UTC).isoformat() + "Z"
    if latency_ms is not None:
        health["latency_ms"] = int(latency_ms)
    if error is not None:
        health["error"] = str(error)


def book_status(book: str | None = None) -> dict[str, Any]:
    """Per-book registry entry merged with live availability.

    Args:
        book: One book slug (e.g. ``"pinnacle"``) or ``None`` for all.

    Returns:
        A mapping of book slug -> ``{name, title, base_url, kind, confidence,
        notes, availability: {reachable, blocked, last_checked, latency_ms,
        error}, sibling?: {book_id, category, method, geo_required}}`` (the
        ``sibling`` block is present only when the sibling BOOKS registry in
        ``sports_data.books`` covers the book). Never raises for unknown
        books (returns ``{}``).
    """
    if book is not None:
        entry = EUROPEAN_BOOKS.get(book)
        if entry is None:
            return {}
        return _status_entry(book, entry)
    return {b: _status_entry(b, EUROPEAN_BOOKS[b]) for b in EUROPEAN_BOOK_ORDER}


def available_books() -> dict[str, dict[str, Any]]:
    """Return only the books whose last fetch was reachable."""
    return {b: s for b, s in book_status().items() if s["availability"].get("reachable", False)}


def book_supports(book: str, sport: str) -> bool:
    """True when a book maps the sport (canonical slug or short alias)."""
    if book not in EUROPEAN_BOOKS or _resolve_sports is None:
        return False
    slugs = _resolve_sports(sport)
    if not slugs:
        return False
    canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
    return canonical in _EUROPEAN_SPORTS


def _canonical_sport(sport: str) -> str | None:
    """Resolve a sport alias to the canonical odds key, or ``None``."""
    if _resolve_sports is None:
        return None
    slugs = _resolve_sports(sport)
    if not slugs:
        return None
    return _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key


# ── Pinnacle (guest JSON API) ───────────────────────────────────────────
_PINNACLE_LEAGUES = "https://guest.api.pinnacle.com/v1/leagues"
_PINNACLE_FIXTURES = "https://guest.api.pinnacle.com/v1/fixtures"
_PINNACLE_ODDS = "https://guest.api.pinnacle.com/v1/odds"
# Pinnacle sport ids (stable public values used by the guest API).
_PINNACLE_SPORTS: dict[str, int] = {
    "americanfootball_nfl": 4,
    "baseball_mlb": 5,
    "basketball_nba": 6,
    "icehockey_nhl": 16,
    "soccer_epl": 29,
    "soccer_spain_la_liga": 29,
    "soccer_germany_bundesliga": 29,
    "soccer_italy_serie_a": 29,
    "soccer_uefa_champions_league": 29,
    "tennis_atp": 33,
    "mma_mixed_martial_arts": 45,
    "boxing": 49,
}
# League-name keywords used to narrow a sport's league list (multi-league
# sports like soccer); empty -> keep every league of the sport.
_PINNACLE_LEAGUE_KEYWORDS: dict[str, str] = {
    "soccer_epl": "premier league",
    "soccer_spain_la_liga": "la liga",
    "soccer_germany_bundesliga": "bundesliga",
    "soccer_italy_serie_a": "serie a",
    "soccer_uefa_champions_league": "champions league",
}


async def _pinnacle_league_ids(sport: str, sport_id: int) -> list[int]:
    """League ids for a sport, narrowed by league keyword when configured."""
    keyword = _PINNACLE_LEAGUE_KEYWORDS.get(sport)
    if keyword is None:
        return []
    url = f"{_PINNACLE_LEAGUES}?{urlencode({'sportId': sport_id})}"
    payload = await _fetch_json_geo(url)
    if not isinstance(payload, dict):
        return []
    leagues = payload.get("leagues")
    if not isinstance(leagues, list):
        return []
    return [
        int(league["id"])
        for league in leagues
        if isinstance(league, dict) and keyword in str(league.get("name") or "").lower()
    ]


def _pinnacle_price(value: Any) -> float | None:
    """Decimal odds from a Pinnacle price (decimal when DECIMAL format)."""
    number = _to_float(value)
    if number is None:
        return None
    if number > 0:
        return round(number, 2)
    # American-format fallback (-110 / +110).
    if _american_to_decimal is None:
        return None
    return _american_to_decimal(value)


async def _parse_pinnacle_sport(
    canonical: str, sport_id: int, league_ids: list[int], limit: int
) -> list[dict[str, Any]]:
    """Fetch fixtures + odds for a Pinnacle sport and join them into records."""
    params: dict[str, Any] = {"sportId": sport_id, "isLive": 0, "oddsFormat": "DECIMAL"}
    if league_ids:
        params["leagueIds"] = ",".join(str(i) for i in league_ids)
    query = urlencode(params)
    fixtures = await _fetch_json_geo(f"{_PINNACLE_FIXTURES}?{query}")
    odds = await _fetch_json_geo(f"{_PINNACLE_ODDS}?{query}")
    events_by_id: dict[int, dict[str, Any]] = {}
    if isinstance(fixtures, dict):
        for league in fixtures.get("leagues") or []:
            if not isinstance(league, dict):
                continue
            for event in league.get("events") or []:
                if isinstance(event, dict) and isinstance(event.get("id"), int):
                    events_by_id[event["id"]] = event
    records: list[dict[str, Any]] = []
    if not isinstance(odds, dict):
        return []
    for league in odds.get("leagues") or []:
        if not isinstance(league, dict):
            continue
        for event in league.get("events") or []:
            if not isinstance(event, dict):
                continue
            event_id = event.get("id")
            fixture = events_by_id.get(event_id) if isinstance(event_id, int) else None
            home = _as_text((fixture or {}).get("home"))
            away = _as_text((fixture or {}).get("away"))
            if not home or not away:
                continue
            last_update = _as_text((fixture or {}).get("starts"))
            event_label = (
                f"{away} @ {home}"
                if _event_label is None
                else (_event_label(home, away) or f"{away} @ {home}")
            )
            periods = event.get("periods")
            if not isinstance(periods, list):
                continue
            for period in periods:
                if not isinstance(period, dict):
                    continue
                moneyline = period.get("moneyline")
                if isinstance(moneyline, dict):
                    home_odds = _pinnacle_price(moneyline.get("home"))
                    away_odds = _pinnacle_price(moneyline.get("away"))
                    if home_odds is not None and away_odds is not None:
                        records.append(
                            sources._record(
                                sport=canonical,
                                event=event_label,
                                event_id=str(event_id),
                                market="h2h",
                                book="pinnacle",
                                bookmaker="Pinnacle",
                                home=home,
                                away=away,
                                home_odds=home_odds,
                                away_odds=away_odds,
                                last_update=last_update,
                                source="european",
                            )
                        )
                spread = period.get("spread")
                if isinstance(spread, dict):
                    line = _to_float(spread.get("hdp"))
                    home_odds = _pinnacle_price(spread.get("home"))
                    away_odds = _pinnacle_price(spread.get("away"))
                    if home_odds is not None and away_odds is not None:
                        records.append(
                            sources._record(
                                sport=canonical,
                                event=event_label,
                                event_id=str(event_id),
                                market="spreads",
                                book="pinnacle",
                                bookmaker="Pinnacle",
                                home=home,
                                away=away,
                                home_odds=home_odds,
                                away_odds=away_odds,
                                spread=line,
                                last_update=last_update,
                                source="european",
                            )
                        )
                total = period.get("total")
                if isinstance(total, dict):
                    line = _to_float(total.get("points"))
                    over_odds = _pinnacle_price(total.get("over"))
                    under_odds = _pinnacle_price(total.get("under"))
                    if over_odds is not None and under_odds is not None:
                        records.append(
                            sources._record(
                                sport=canonical,
                                event=event_label,
                                event_id=str(event_id),
                                market="totals",
                                book="pinnacle",
                                bookmaker="Pinnacle",
                                home=home,
                                away=away,
                                home_odds=over_odds,
                                away_odds=under_odds,
                                total=line,
                                last_update=last_update,
                                source="european",
                            )
                        )
    return records[: max(1, int(limit or 50))]


async def fetch_pinnacle(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Pinnacle odds for one sport via the guest JSON API.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``).
        limit: Max records to return.

    Returns:
        Canonical h2h/spreads/totals records tagged ``source="european"``;
        ``[]`` on any failure. Never raises.
    """
    name = "pinnacle"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        sport_id = _PINNACLE_SPORTS.get(canonical)
        if sport_id is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        league_ids = await _pinnacle_league_ids(canonical, sport_id)
        records = await _parse_pinnacle_sport(canonical, sport_id, league_ids, limit)
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── Marathonbet (server-rendered coupon) ────────────────────────────────
_MARATHON_SPORTS: dict[str, str] = {
    "americanfootball_nfl": "American-Football",
    "baseball_mlb": "Baseball",
    "basketball_nba": "Basketball",
    "icehockey_nhl": "Ice-Hockey",
    "soccer_epl": "Football",
    "soccer_spain_la_liga": "Football",
    "soccer_germany_bundesliga": "Football",
    "soccer_italy_serie_a": "Football",
    "soccer_uefa_champions_league": "Football",
    "tennis_atp": "Tennis",
    "mma_mixed_martial_arts": "MMA",
    "boxing": "Boxing",
}


async def fetch_marathonbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Marathonbet odds for one sport from the coupon pages.

    Marathonbet serves decimal-odds HTML rows (``coupon-row``) with the
    three-way (soccer) or two-way (NBA) layout; parsed by the generic
    decimal-rows parser shared with the offshore module.
    """
    name = "marathonbet"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        path = _MARATHON_SPORTS.get(canonical)
        if path is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        url = f"{EUROPEAN_BOOKS[name]['base_url']}/{path}/"
        html = await _fetch_text_geo(url)
        if html is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if offshore._looks_blocked(html):
            _mark_book(
                name,
                ok=False,
                blocked=True,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="anti-bot/geo block",
            )
            return []
        records = _parse_decimal_rows(html, canonical, name, "Marathonbet")
        for record in records:
            record["source"] = "european"
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── 1xBet (internal LineFeed JSON) ──────────────────────────────────────
_1XBET_SPORTS: dict[str, int] = {
    "soccer_epl": 1,
    "soccer_spain_la_liga": 1,
    "soccer_germany_bundesliga": 1,
    "soccer_italy_serie_a": 1,
    "soccer_uefa_champions_league": 1,
    "tennis_atp": 2,
    "baseball_mlb": 3,
    "basketball_nba": 4,
    "icehockey_nhl": 5,
    "americanfootball_nfl": 7,
    "boxing": 9,
    "mma_mixed_martial_arts": 10,
}
_1XBET_LEAGUE_KEYWORDS: dict[str, str] = {
    "soccer_epl": "premier league",
    "soccer_spain_la_liga": "la liga",
    "soccer_germany_bundesliga": "bundesliga",
    "soccer_italy_serie_a": "serie a",
    "soccer_uefa_champions_league": "champions league",
}


def _decode_1xbet_payload(payload: dict[str, Any]) -> Any | None:
    """Decode the 1xBet ``Value`` field (base64 -> gzip/zlib -> JSON)."""
    value = payload.get("Value")
    if not isinstance(value, str) or not value:
        return None
    try:
        raw = base64.b64decode(value)
    except (ValueError, TypeError):
        return None
    for decompressor in (gzip.decompress, zlib.decompress):
        try:
            return json.loads(decompressor(raw).decode("utf-8", "replace"))
        except (OSError, zlib.error, json.JSONDecodeError, UnicodeDecodeError):
            continue
    return None


def _parse_1xbet_payload(data: Any, canonical: str, keyword: str | None) -> list[dict[str, Any]]:
    """Map the decoded LineFeed JSON onto h2h records.

    Structure: ``L`` = leagues [{id, I: name}], ``E`` = events
    [{id, L: league id, S: start, T: [{N: team}...], G: [group]}] where the
    first group (``G == "1"``) holds the match-winner outcomes
    (``T`` in {1, X, 2}, ``P: {"1": decimal}``).
    """
    if not isinstance(data, dict):
        return []
    leagues: dict[Any, str] = {}
    for league in data.get("L") or []:
        if isinstance(league, dict) and isinstance(league.get("id"), int):
            leagues[league["id"]] = str(league.get("I") or "")
    records: list[dict[str, Any]] = []
    for event in data.get("E") or []:
        if not isinstance(event, dict):
            continue
        league_name = leagues.get(event.get("L"))
        if keyword and league_name and keyword not in league_name.lower():
            continue
        teams_raw = event.get("T") or []
        teams = [str(t.get("N") or "") for t in teams_raw if isinstance(t, dict) and t.get("N")]
        if len(teams) < 2:
            continue
        away, home = teams[0], teams[1]  # 1xBet lists participants away-first
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        outcomes: dict[str, float] = {}
        groups = event.get("G") or []
        for group in groups:
            if not isinstance(group, dict):
                continue
            if str(group.get("G") or "") != "1":
                continue
            for outcome in group.get("E") or []:
                if not isinstance(outcome, dict):
                    continue
                key = str(outcome.get("T") or "")
                price = outcome.get("P")
                if not isinstance(price, dict):
                    continue
                value = _to_float(price.get("1"))
                if value is not None and value > 1:
                    outcomes[key] = round(value, 2)
            break
        home_odds = outcomes.get("1")
        away_odds = outcomes.get("2")
        if home_odds is None or away_odds is None:
            continue
        records.append(
            sources._record(  # type: ignore[attr-defined]
                sport=canonical,
                event=event_label,
                event_id=str(event.get("id")),
                market="h2h",
                book="1xbet",
                bookmaker="1xBet",
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                draw_odds=outcomes.get("X"),
                last_update=_as_text(event.get("S")),
                source="european",
            )
        )
    return records


async def fetch_1xbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch 1xBet odds for one sport via the internal LineFeed endpoint."""
    name = "1xbet"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        sport_id = _1XBET_SPORTS.get(canonical)
        if sport_id is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        query = urlencode(
            {
                "sport": sport_id,
                "lng": "en",
                "tf": "2200000",
                "tz": "3",
                "mode": "4",
                "country": "1",
            }
        )
        url = f"{EUROPEAN_BOOKS[name]['base_url']}/Get1x2_VZip?{query}"
        payload = await _fetch_json_geo(url)
        if not isinstance(payload, dict):
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        data = _decode_1xbet_payload(payload)
        records = _parse_1xbet_payload(data, canonical, _1XBET_LEAGUE_KEYWORDS.get(canonical))
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── Betfair (public read-only Exchange API) ─────────────────────────────
_BETFAIR_EXCHANGE = "https://www.betfair.com/exchange/plus"
_BETFAIR_READONLY = "https://www.betfair.com/www/sports/exchange/readonly/v1"
# Public access key embedded in Betfair's own frontend (documented by the
# community scrapers); refresh if Betfair rotates it — [REVIEW].
_BETFAIR_AK = "nzIFcwyWhrlwYMrh"
_BETFAIR_TYPES = (
    "MARKET_STATE,RUNNER_STATE,RUNNER_EXCHANGE_PRICES_BEST,"
    "RUNNER_DESCRIPTION,MARKET_RATES,MARKET_DESCRIPTION,EVENT,RUNNER_METADATA"
)
_BETFAIR_SPORTS: dict[str, str] = {
    "americanfootball_nfl": "american-football",
    "baseball_mlb": "baseball",
    "basketball_nba": "basketball",
    "icehockey_nhl": "ice-hockey",
    "soccer_epl": "football",
    "soccer_spain_la_liga": "football",
    "soccer_germany_bundesliga": "football",
    "soccer_italy_serie_a": "football",
    "soccer_uefa_champions_league": "football",
    "tennis_atp": "tennis",
    "mma_mixed_martial_arts": "mma",
    "boxing": "boxing",
}
_MARKET_ID_RE = re.compile(r'"marketId"\s*:\s*"(\d+\.\d+)"')


def _discover_market_ids(html: str, limit: int) -> list[str]:
    """Unique market ids embedded in an exchange page (in page order)."""
    seen: list[str] = []
    for market_id in _MARKET_ID_RE.findall(html or ""):
        if market_id not in seen:
            seen.append(market_id)
    return seen[: max(1, int(limit or 50))]


def _parse_betfair_markets(payload: Any, canonical: str) -> list[dict[str, Any]]:
    """Map the bymarket response (eventTypes/eventNodes/marketNodes) to h2h records.

    Runner order is used as the home/away/draw convention — Betfair lists
    runners in selection order, so this is best-effort: [REVIEW] a name
    match against a fixture list for reliable home/away attribution.
    """
    if not isinstance(payload, dict):
        return []
    records: list[dict[str, Any]] = []
    for event_type in payload.get("eventTypes") or []:
        if not isinstance(event_type, dict):
            continue
        for event_node in event_type.get("eventNodes") or []:
            if not isinstance(event_node, dict):
                continue
            event_name = _as_text((event_node.get("event") or {}).get("name"))
            for market_node in event_node.get("marketNodes") or []:
                if not isinstance(market_node, dict):
                    continue
                market_name = str(market_node.get("marketName") or "")
                if not re.search(r"match odds|match winner|1x2|2-way", market_name, re.I):
                    continue
                runners = market_node.get("runners") or []
                if not isinstance(runners, list) or len(runners) < 2:
                    continue
                back_prices: list[float] = []
                runner_names: list[str] = []
                for runner in runners:
                    if not isinstance(runner, dict):
                        continue
                    runner_names.append(str(runner.get("runnerName") or ""))
                    exchange = runner.get("exchange")
                    price = None
                    if isinstance(exchange, dict):
                        best = exchange.get("availableToBack") or []
                        if isinstance(best, list) and best and isinstance(best[0], dict):
                            price = _to_float(best[0].get("price"))
                    back_prices.append(price if price is not None else 0.0)
                prices = [p for p in back_prices if p > 0]
                if len(prices) < 2:
                    continue
                home = runner_names[0] or (event_name or "")
                away = runner_names[1] or ""
                draw_odds = back_prices[2] if len(back_prices) >= 3 and back_prices[2] > 0 else None
                if not home or not away:
                    continue
                event_label = (
                    f"{away} @ {home}"
                    if _event_label is None
                    else (_event_label(home, away) or f"{away} @ {home}")
                )
                records.append(
                    sources._record(  # type: ignore[attr-defined]
                        sport=canonical,
                        event=event_label,
                        event_id=str(market_node.get("marketId") or ""),
                        market="h2h",
                        book="betfair",
                        bookmaker="Betfair",
                        home=home,
                        away=away,
                        home_odds=back_prices[0] or None,
                        away_odds=back_prices[1] or None,
                        draw_odds=draw_odds,
                        last_update=None,
                        source="european",
                    )
                )
    return records


async def fetch_betfair(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Betfair Exchange back odds for one sport via the read-only API.

    Discovers market ids from the exchange page, then pulls prices from the
    public ``bymarket`` endpoint (no login). Cloudflare-protected — a
    Webshare proxy retry is attempted when the direct request is blocked.
    """
    name = "betfair"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        path = _BETFAIR_SPORTS.get(canonical)
        if path is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        page = await _fetch_text_geo(f"{_BETFAIR_EXCHANGE}/{path}")
        if page is None or offshore._looks_blocked(page):
            _mark_book(
                name,
                ok=False,
                blocked=True,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="anti-bot/geo block",
            )
            return []
        market_ids = _discover_market_ids(page, limit)
        if not market_ids:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no markets discovered",
            )
            return []
        query = urlencode(
            {
                "_ak": _BETFAIR_AK,
                "marketIds": ",".join(market_ids),
                "currencyCode": "USD",
                "locale": "en_GB",
                "rollupLimit": "2",
                "rollupModel": "STAKE",
                "types": _BETFAIR_TYPES,
                "alt": "json",
            }
        )
        payload = await _fetch_json_geo(f"{_BETFAIR_READONLY}/bymarket?{query}")
        records = _parse_betfair_markets(payload, canonical)
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── Generic embedded/html books (Betway, 10Bet, SBOBet, Dafabet, 12Bet, W88)


def _generic_book_url(book: str, canonical: str) -> str | None:
    """Best-effort odds-page URL for a generic book; ``None`` when unsupported."""
    route = _EUROPEAN_SPORTS.get(canonical)
    if route is None:
        return None
    sport_slug, league = route
    base = EUROPEAN_BOOKS[book]["base_url"]
    # SBOBet uses bare sport paths (www.sbobet.com/tennis); the others append
    # an optional league segment.
    if book == "sbobet":
        return f"{base}/{sport_slug}"
    url = f"{base}/{sport_slug}"
    if league:
        url = f"{url}/{league}"
    return url


async def _fetch_generic_book(sport: str, book: str, limit: int) -> list[dict[str, Any]]:
    """Fetch a generic book: embedded state first, then decimal HTML rows."""
    start = offshore._monotonic()
    try:
        if book not in EUROPEAN_BOOKS:
            return []
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        url = _generic_book_url(book, canonical)
        if url is None:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        html = await _fetch_text_geo(url)
        if html is None:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if offshore._looks_blocked(html):
            logger.warning("sports_european_blocked", extra={"book": book, "sport": sport})
            _mark_book(
                book,
                ok=False,
                blocked=True,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="anti-bot/geo block",
            )
            return []
        bookmaker = str(EUROPEAN_BOOKS[book]["title"])
        records = _parse_embedded_state(html, canonical, book, bookmaker)
        if not records:
            records = _parse_decimal_rows(html, canonical, book, bookmaker)
        for record in records:
            record["source"] = "european"
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(book, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": book, "sport": sport})
        _mark_book(
            book,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── Per-book fetchers (public) ──────────────────────────────────────────


async def fetch_betway(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Betway odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "betway", limit)


async def fetch_10bet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch 10Bet odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "10bet", limit)


async def fetch_sbobet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch SBOBet odds for one sport (best-effort; often geo-blocked)."""
    return await _fetch_generic_book(sport, "sbobet", limit)


async def fetch_dafabet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Dafabet odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "dafabet", limit)


async def fetch_12bet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch 12Bet odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "12bet", limit)


async def fetch_w88(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch W88 odds for one sport (best-effort)."""
    return await _fetch_generic_book(sport, "w88", limit)


# ── Aggregate ───────────────────────────────────────────────────────────


async def fetch_european_odds(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Aggregate odds for one sport across every European book.

    Runs all per-book fetchers concurrently. One dead or geo-blocked book
    never affects the others.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``
            or ``"nba"``).
        limit: Max records to parse per book (matches the per-source cap
            convention in ``sports_data.sources``).

    Returns:
        Canonical odds records from every reachable book; ``[]`` on any
        failure. Never raises.
    """
    try:
        fetchers: list[Any] = [_fetch_book(sport, book, limit) for book in EUROPEAN_BOOK_ORDER]
        results = await asyncio.gather(*fetchers, return_exceptions=True)
    except (httpx.HTTPError, OSError, ValueError):
        return []
    records: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        if not isinstance(result, list):
            continue
        records.extend(record for record in result if isinstance(record, dict))
    return records


# Book-specific dispatch used by the aggregate (each never raises).
async def _fetch_book(sport: str, book: str, limit: int) -> list[dict[str, Any]]:
    if book == "pinnacle":
        return await fetch_pinnacle(sport, limit)
    if book == "marathonbet":
        return await fetch_marathonbet(sport, limit)
    if book == "1xbet":
        return await fetch_1xbet(sport, limit)
    if book == "betfair":
        return await fetch_betfair(sport, limit)
    return await _fetch_generic_book(sport, book, limit)
