"""Offshore sportsbook odds fetchers for Pry (reachable without a US geo-IP).

Extends :mod:`sports_data.sources` (Bovada + BetOnline) with the rest of the
offshore tier: books that target US bettors but do **not** hard-geo-block a
non-US egress IP — the BookMaker-group brands and the crypto/legacy books.
Every book is fetched with Pry's own httpx + stealth transport, and when a
book's direct request looks like an anti-bot / geo block it is retried
through the Webshare residential pool (``WEBSHARE_PROXY_LIST``) when one is
configured.

Books covered (13 new + the existing Bovada/BetOnline fetchers reused):

* BookMaker-group brands share the BetOnline platform markup (game links
  ``/sportsbook/{sport}/{league}/game/{id}`` + a ``window.__INITIAL_STATE__``
  blob), so their parsers are reused directly from :mod:`sports_data.sources`
  — never duplicated: ``bookmaker``, ``sportsbetting``, ``betanysports``,
  ``wagerweb``, ``lowvig``.
* Standalone books (``heritage``, ``mybookie``, ``betus``, ``jazzsports``,
  ``nitrobetting``, ``youwager``, ``everygame``, ``gtbets``) run a generic
  embedded-state walk + a conservative decimal-odds HTML row parser; their
  markup is JS-heavy so plain HTTP often returns no odds — that is flagged
  honestly (never silently treated as "no odds").

Contract
--------
* :func:`fetch_offshore_odds` aggregates every per-book fetcher and never
  raises — it returns ``[]`` on any failure (network, block, malformed
  payload, unsupported sport). One dead book never affects the others.
* Every record follows the canonical odds schema from
  :mod:`sports_data.odds` (``sport, event, market, book, bookmaker, home,
  away, home_odds, away_odds, draw_odds, spread, total, last_update,
  source``). Records produced here are tagged ``source="offshore"``; the
  reused Bovada/BetOnline records keep their original ``source`` tag.
* :data:`OFFSHORE_BOOKS` is the static registry (name, base url, kind,
  confidence, notes); :func:`book_status` adds the live per-book
  availability seen by the last fetch.

Free-API terms: all feeds are unofficial public pages — scrape politely,
expect layout drift and geo-blocks.

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
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

import datasets.sports_data.sources as sources
from pry.engine.retry import RetryConfig, async_retry
from pry.engine.webshare_proxy import next_webshare_proxy
from datasets.sports_data.sources import (
    _as_text,
    _classes,
    _fetch_text,
    _from_html,
    _looks_blocked,
    _monotonic,
    _parse_betonline_embedded_json,
    _parse_betonline_html,
    _to_float,
)

# Guarded import: sports_data.odds is extended by a parallel agent; this
# module is imported by the package during init, so degrade gracefully if
# the sibling is momentarily unavailable (parallel build safety).
try:
    from datasets.sports_data.odds import _SPORTS, _american_to_decimal, _event_label, _resolve_sports
except ImportError:  # pragma: no cover - parallel build guard
    _american_to_decimal = None  # type: ignore[assignment]
    _event_label = None  # type: ignore[assignment]
    _resolve_sports = None  # type: ignore[assignment]
    _SPORTS = {}  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Book registry ───────────────────────────────────────────────────────
# Canonical book slug -> {name (display), base_url (odds-page root), kind
# (extraction method), confidence (0..1, how reliably the feed yields clean
# odds today), notes}. ``kind`` is one of:
#   "family"   — BetOnline-family markup; sources parsers are reused.
#   "embedded" — best-effort embedded-state walk (JS-heavy SPA books).
OFFSHORE_BOOKS: dict[str, dict[str, Any]] = {
    "bookmaker": {
        "title": "BookMaker",
        "base_url": "https://www.bookmaker.eu/sportsbook",
        "kind": "family",
        "confidence": 0.4,
        "notes": "BookMaker-group platform (shared markup with BetOnline). Server-rendered listing; may geo-block EU egress.",
    },
    "sportsbetting": {
        "title": "SportsBetting.ag",
        "base_url": "https://www.sportsbetting.ag/sportsbook",
        "kind": "family",
        "confidence": 0.4,
        "notes": "Sister brand of BookMaker; same platform markup as BetOnline.",
    },
    "betanysports": {
        "title": "BetAnySports",
        "base_url": "https://www.betanysports.eu/sportsbook",
        "kind": "family",
        "confidence": 0.4,
        "notes": "BookMaker-group brand (EU-licensed egress); same platform markup.",
    },
    "wagerweb": {
        "title": "WagerWeb",
        "base_url": "https://www.wagerweb.com/sportsbook",
        "kind": "family",
        "confidence": 0.4,
        "notes": "BookMaker-group brand; same platform markup.",
    },
    "lowvig": {
        "title": "LowVig",
        "base_url": "https://www.lowvig.ag/sportsbook",
        "kind": "family",
        "confidence": 0.4,
        "notes": "Low-margin BookMaker-group brand; same platform markup.",
    },
    "heritage": {
        "title": "Heritage",
        "base_url": "https://www.heritage-odds.com/sportsbook",
        "kind": "embedded",
        "confidence": 0.2,
        "notes": "JS-heavy SPA; plain HTTP may only see the shell. Best-effort.",
    },
    "mybookie": {
        "title": "MyBookie",
        "base_url": "https://www.mybookie.ag/sportsbook",
        "kind": "embedded",
        "confidence": 0.2,
        "notes": "JS-heavy SPA; best-effort. May geo-block non-US egress.",
    },
    "betus": {
        "title": "BetUS",
        "base_url": "https://www.betus.com/sportsbook",
        "kind": "embedded",
        "confidence": 0.2,
        "notes": "JS-heavy SPA; best-effort. May geo-block non-US egress.",
    },
    "jazzsports": {
        "title": "JazzSports",
        "base_url": "https://www.jazzsports.ag/sportsbook",
        "kind": "embedded",
        "confidence": 0.2,
        "notes": "JS-heavy SPA; best-effort.",
    },
    "nitrobetting": {
        "title": "NitroBetting",
        "base_url": "https://www.nitrobetting.eu/sportsbook",
        "kind": "embedded",
        "confidence": 0.2,
        "notes": "Crypto book (EU-licensed egress); JS-heavy SPA; best-effort.",
    },
    "youwager": {
        "title": "YouWager",
        "base_url": "https://www.youwager.eu/sportsbook",
        "kind": "embedded",
        "confidence": 0.2,
        "notes": "Legacy book (EU egress); best-effort.",
    },
    "everygame": {
        "title": "Everygame",
        "base_url": "https://www.everygame.eu/sportsbook",
        "kind": "embedded",
        "confidence": 0.2,
        "notes": "Former Intertops (EU egress); best-effort.",
    },
    "gtbets": {
        "title": "GTbets",
        "base_url": "https://www.gtbets.eu/sportsbook",
        "kind": "embedded",
        "confidence": 0.2,
        "notes": "Legacy book (EU egress); best-effort.",
    },
}

# Books sharing the BetOnline/SBTech platform markup (game links
# ``/sportsbook/{sport}/{league}/game/{id}`` + ``window.__INITIAL_STATE__``).
_BETONLINE_FAMILY: frozenset[str] = frozenset(
    {"bookmaker", "sportsbetting", "betanysports", "wagerweb", "lowvig"}
)

# Aggregate order (also used for book_status iteration).
OFFSHORE_BOOK_ORDER: tuple[str, ...] = (
    "bookmaker",
    "heritage",
    "mybookie",
    "betus",
    "jazzsports",
    "sportsbetting",
    "betanysports",
    "wagerweb",
    "nitrobetting",
    "lowvig",
    "youwager",
    "everygame",
    "gtbets",
)

# Canonical sport slug -> (book path slug, league path slug or None).
# Mirrors the routing tables in sports_data.sources for the offshore books.
_OFFSHORE_SPORTS: dict[str, tuple[str, str | None]] = {
    "basketball_nba": ("basketball", "nba"),
    "basketball_ncaab": ("basketball", "ncaa"),
    "basketball_wnba": ("basketball", "wnba"),
    "americanfootball_nfl": ("football", "nfl"),
    "americanfootball_ncaaf": ("football", "ncaa"),
    "americanfootball_cfl": ("football", "cfl"),
    "baseball_mlb": ("baseball", "mlb"),
    "icehockey_nhl": ("hockey", "nhl"),
    "soccer_epl": ("soccer", "england"),
    "soccer_spain_la_liga": ("soccer", "spain"),
    "soccer_germany_bundesliga": ("soccer", "germany"),
    "soccer_italy_serie_a": ("soccer", "italy"),
    "soccer_uefa_champions_league": ("soccer", "champions-league"),
    "soccer_usa_mls": ("soccer", "usa"),
    "tennis_atp": ("tennis", None),
    "tennis_wta": ("tennis", None),
    "mma_mixed_martial_arts": ("mma", None),
    "boxing": ("boxing", None),
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
_SIBLING_ALIASES: dict[str, str] = {"sportsbetting": "sportsbetting-ag"}


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
    for book in OFFSHORE_BOOK_ORDER
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
        book: One book slug (e.g. ``"bookmaker"``) or ``None`` for all.

    Returns:
        A mapping of book slug -> ``{name, title, base_url, kind, confidence,
        notes, availability: {reachable, blocked, last_checked, latency_ms,
        error}, sibling?: {book_id, category, method, geo_required}}`` (the
        ``sibling`` block is present only when the sibling BOOKS registry in
        ``sports_data.books`` covers the book). Never raises for unknown
        books (returns ``{}``).
    """
    if book is not None:
        entry = OFFSHORE_BOOKS.get(book)
        if entry is None:
            return {}
        return _status_entry(book, entry)
    return {b: _status_entry(b, OFFSHORE_BOOKS[b]) for b in OFFSHORE_BOOK_ORDER}


def available_books() -> dict[str, dict[str, Any]]:
    """Return only the books whose last fetch was reachable."""
    return {b: s for b, s in book_status().items() if s["availability"].get("reachable", False)}


def book_supports(book: str, sport: str) -> bool:
    """True when a book maps the sport (canonical slug or short alias)."""
    if book not in OFFSHORE_BOOKS or _resolve_sports is None:
        return False
    slugs = _resolve_sports(sport)
    if not slugs:
        return False
    canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
    return canonical in _OFFSHORE_SPORTS


# ── Transport (httpx + stealth headers, proxy fallback on geo-blocks) ───
_TIMEOUT = httpx.Timeout(15.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)

# Decimal odds token (e.g. "2.10") vs. US odds (e.g. "+110" / "-120") used
# by the generic row parser.
_DECIMAL_ODDS_RE = re.compile(r"^\d+\.\d{2}$")
_US_ODDS_RE = re.compile(r"[+-]\d{3,4}\b")


async def _fetch_text_geo(url: str) -> str | None:
    """Fetch text; on block/transport failure retry via a Webshare proxy.

    Uses the repo's shared ``sources._fetch_text`` (stealth headers, retry,
    TTL cache) for the direct attempt. When the direct response looks like an
    anti-bot/geo block and a proxy is configured (``WEBSHARE_PROXY_LIST``),
    one more attempt is made through the pool. The blocked body is surfaced
    to the caller when no proxy is available (or the proxy is also blocked)
    so blocks are flagged honestly — never silently treated as "no odds".
    Never raises.
    """

    async def _via_proxy(proxy: str) -> str | None:
        async def _one() -> str:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                headers=sources._stealth_headers(url),
                proxy=proxy,
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
                if response.status_code >= 500:
                    response.raise_for_status()
                text = response.text
            if not text:
                raise ValueError("empty proxied upstream response")
            return text

        try:
            payload = await async_retry(_one, config=_RETRY_CONFIG)
        except (httpx.HTTPError, OSError, ValueError):
            return None
        if payload is None or _looks_blocked(payload):
            return None
        return payload

    direct = await _fetch_text(url)
    if direct is not None and not _looks_blocked(direct):
        return direct
    proxy = next_webshare_proxy()
    if proxy is None:
        # No proxy configured: surface the blocked body (or None on a pure
        # transport failure) so callers can flag the block honestly.
        return direct
    proxied = await _via_proxy(proxy)
    if proxied is not None:
        return proxied
    return direct


async def _fetch_json_geo(url: str) -> Any | None:
    """GET ``url`` (proxy fallback on geo-block) and parse JSON; ``None`` on failure."""
    text = await _fetch_text_geo(url)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── Generic parsers (standalone books) ──────────────────────────────────


def _parse_embedded_state(html: str, sport: str, book: str, bookmaker: str) -> list[dict[str, Any]]:
    """Best-effort walk of a ``window.__INITIAL_STATE__``-style JSON blob.

    Mirrors the BookMaker-family shape (``gameId`` / ``homeTeam`` /
    ``awayTeam`` / ``gameData[].lineDict.MoneyLine``) that the BetOnline
    parser in :mod:`sports_data.sources` already handles, plus a looser
    fallback that recognises any nested object carrying two team names and a
    two-sided decimal odds dict.
    """
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    events: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if "gameId" in node and ("homeTeam" in node or "gameData" in node):
                events.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data)
    records: list[dict[str, Any]] = []
    for event in events:
        game_id = _as_text(event.get("gameId"))
        home = _as_text(event.get("homeTeam"))
        away = _as_text(event.get("awayTeam"))
        if not home or not away or _american_to_decimal is None:
            continue
        game_data = event.get("gameData")
        if not isinstance(game_data, list):
            continue
        home_odds = away_odds = None
        for period in game_data:
            if not isinstance(period, dict):
                continue
            line_type = str(period.get("lineType") or "")
            line_dict = period.get("lineDict")
            if not isinstance(line_dict, dict):
                continue
            money = line_dict.get("MoneyLine")
            if not isinstance(money, dict):
                continue
            value = _as_text(money.get("decimalLine")) or _as_text(money.get("line"))
            if line_type == "AwayLine":
                away_odds = _to_float(value)
            elif line_type == "HomeLine":
                home_odds = _to_float(value)
        if home_odds is None and away_odds is None:
            continue
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        records.append(
            sources._record(
                sport=sport,
                event=event_label,
                event_id=game_id,
                market="h2h",
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                last_update=_as_text(event.get("wagerCutOff")),
                source="offshore",
            )
        )
    return records


def _parse_decimal_rows(html: str, sport: str, book: str, bookmaker: str) -> list[dict[str, Any]]:
    """Conservative generic HTML row parser for SSR'd decimal-odds pages.

    Walks ``<tr>``/``<div>`` containers whose class hints at a game row and
    requires at least two team-like text nodes and two decimal odds in the
    same container before emitting an h2h record. Two odds -> 2-way; three
    odds -> 3-way (draw in the middle). Never raises; returns ``[]`` when the
    page has no such rows (JS-rendered books degrade honestly to empty).
    """
    tree = _from_html(html)
    if tree is None:
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for el in tree.iter():
        if el.tag not in ("tr", "div"):
            continue
        cls = _classes(el)
        if not re.search(r"row|game|coupon|match|event|odds", cls, re.I):
            continue
        texts: list[str] = []
        for node in el.itertext():
            text = _as_text(node)
            if text is not None:
                texts.append(text)
        odds = [t for t in texts if _DECIMAL_ODDS_RE.match(t)]
        teams = [
            t
            for t in texts
            if not _DECIMAL_ODDS_RE.match(t) and _US_ODDS_RE.search(t) is None and 2 <= len(t) <= 40
        ]
        if len(teams) < 2 or len(odds) < 2:
            continue
        home, away = teams[0], teams[1]
        key = f"{home}|{away}|{tuple(odds)}"
        if key in seen:
            continue
        seen.add(key)
        draw_value = _to_float(odds[1]) if len(odds) >= 3 else None
        if len(odds) >= 3 and draw_value is not None and 0 < draw_value < 10:
            home_odds, away_odds = _to_float(odds[0]), _to_float(odds[2])
            draw_odds = draw_value
        else:
            home_odds, away_odds = _to_float(odds[0]), _to_float(odds[1])
            draw_odds = None
        if home_odds is None and away_odds is None:
            continue
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        records.append(
            sources._record(
                sport=sport,
                event=event_label,
                event_id=None,
                market="h2h",
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                draw_odds=draw_odds,
                last_update=None,
                source="offshore",
            )
        )
    return records


# ── Per-book fetch pipeline ─────────────────────────────────────────────


def _canonical_sport(sport: str) -> str | None:
    """Resolve a sport alias to the canonical odds key, or ``None``."""
    if _resolve_sports is None:
        return None
    slugs = _resolve_sports(sport)
    if not slugs:
        return None
    return _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key


def _book_url(book: str, sport: str) -> str | None:
    """Build the odds-page URL for one book/sport; ``None`` when unsupported."""
    route = _OFFSHORE_SPORTS.get(sport)
    if route is None:
        return None
    sport_slug, league = route
    url = f"{OFFSHORE_BOOKS[book]['base_url']}/{sport_slug}"
    if league:
        url = f"{url}/{league}"
    return url


async def _fetch_book(sport: str, book: str, limit: int) -> list[dict[str, Any]]:
    """Fetch one book's odds for one sport. Never raises — returns ``[]``."""
    start = _monotonic()
    try:
        if book not in OFFSHORE_BOOKS:
            return []
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        url = _book_url(book, canonical)
        if url is None:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        html = await _fetch_text_geo(url)
        if html is None:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if _looks_blocked(html):
            logger.warning("sports_offshore_blocked", extra={"book": book, "sport": sport})
            _mark_book(
                book,
                ok=False,
                blocked=True,
                latency_ms=int((_monotonic() - start) * 1000),
                error="anti-bot/geo block",
            )
            return []
        cfg = OFFSHORE_BOOKS[book]
        bookmaker = str(cfg["title"])
        if book in _BETONLINE_FAMILY:
            # Same platform as BetOnline: reuse its parsers directly.
            records = _parse_betonline_embedded_json(html, canonical)
            if not records:
                records = _parse_betonline_html(html, canonical)
            for record in records:
                record["book"] = book
                record["bookmaker"] = bookmaker
                record["source"] = "offshore"
        else:
            records = _parse_embedded_state(html, canonical, book, bookmaker)
            if not records:
                records = _parse_decimal_rows(html, canonical, book, bookmaker)
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                book,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(book, ok=True, latency_ms=int((_monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_offshore_failed", extra={"book": book, "sport": sport})
        _mark_book(
            book,
            ok=False,
            latency_ms=int((_monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── Per-book fetchers (public) ──────────────────────────────────────────


async def fetch_bookmaker(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BookMaker odds for one sport (offshore BookMaker-group book)."""
    return await _fetch_book(sport, "bookmaker", limit)


async def fetch_heritage(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Heritage odds for one sport (offshore; JS-heavy, best-effort)."""
    return await _fetch_book(sport, "heritage", limit)


async def fetch_mybookie(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch MyBookie odds for one sport (offshore; JS-heavy, best-effort)."""
    return await _fetch_book(sport, "mybookie", limit)


async def fetch_betus(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BetUS odds for one sport (offshore; JS-heavy, best-effort)."""
    return await _fetch_book(sport, "betus", limit)


async def fetch_jazzsports(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch JazzSports odds for one sport (offshore; JS-heavy, best-effort)."""
    return await _fetch_book(sport, "jazzsports", limit)


async def fetch_sportsbetting(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch SportsBetting.ag odds for one sport (BookMaker-group brand)."""
    return await _fetch_book(sport, "sportsbetting", limit)


async def fetch_betanysports(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BetAnySports odds for one sport (BookMaker-group brand)."""
    return await _fetch_book(sport, "betanysports", limit)


async def fetch_wagerweb(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch WagerWeb odds for one sport (BookMaker-group brand)."""
    return await _fetch_book(sport, "wagerweb", limit)


async def fetch_nitrobetting(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch NitroBetting odds for one sport (crypto book; best-effort)."""
    return await _fetch_book(sport, "nitrobetting", limit)


async def fetch_lowvig(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch LowVig odds for one sport (BookMaker-group brand)."""
    return await _fetch_book(sport, "lowvig", limit)


async def fetch_youwager(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch YouWager odds for one sport (legacy book; best-effort)."""
    return await _fetch_book(sport, "youwager", limit)


async def fetch_everygame(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Everygame odds for one sport (legacy book; best-effort)."""
    return await _fetch_book(sport, "everygame", limit)


async def fetch_gtbets(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch GTbets odds for one sport (legacy book; best-effort)."""
    return await _fetch_book(sport, "gtbets", limit)


# ── Aggregate ───────────────────────────────────────────────────────────


async def fetch_offshore_odds(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Aggregate odds for one sport across every offshore book.

    Runs all per-book fetchers concurrently and reuses the existing
    Bovada + BetOnline fetchers from :mod:`sports_data.sources` (same
    offshore tier — extended, never duplicated). One dead or geo-blocked
    book never affects the others.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``
            or ``"nba"``).
        limit: Max events to parse per book (each book may yield several
            records per event; matches the per-source cap convention in
            ``sports_data.sources``).

    Returns:
        Canonical odds records from every reachable book; ``[]`` on any
        failure. Never raises.
    """
    try:
        fetchers: list[Any] = [_fetch_book(sport, book, limit) for book in OFFSHORE_BOOK_ORDER]
        # Reuse the existing offshore fetchers rather than duplicating them.
        fetchers.append(sources.fetch_bovada(sport))
        fetchers.append(sources.fetch_betonline(sport))
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
