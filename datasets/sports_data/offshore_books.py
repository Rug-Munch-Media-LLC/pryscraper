"""Offshore sportsbook registry, sport routing, and live availability.

Static registry (:data:`OFFSHORE_BOOKS`) of the offshore tier books that
target US bettors but do **not** hard-geo-block a non-US egress IP — the
BookMaker-group brands and the crypto/legacy books — plus the canonical
sport-slug routing table and the live per-book availability tracking
(:func:`book_status`, :func:`available_books`, :func:`book_supports`).

``kind`` values in the registry:
  "family"   — BetOnline-family markup; sources parsers are reused.
  "embedded" — best-effort embedded-state walk (JS-heavy SPA books).

Guarded reuse of the sibling BOOKS registry (sports_data.books) and the
sibling odds helpers (sports_data.odds) degrades gracefully when those
parallel-built modules are momentarily unavailable.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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

# ── Book registry ───────────────────────────────────────────────────────
# Canonical book slug -> {name (display), base_url (odds-page root), kind
# (extraction method), confidence (0..1, how reliably the feed yields clean
# odds today), notes}.
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
# The sibling BOOKS registry lookup (sports_data.books) is delegated to
# ``offshore._sibling_entry`` (kept in the facade module so tests can
# monkeypatch ``offshore._SIBLING_BOOKS`` — same pattern as european_common).


def _status_entry(book: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Registry entry + live availability + optional sibling annotation.

    The sibling lookup is delegated to ``offshore._sibling_entry`` (kept in
    the facade module so tests can monkeypatch ``offshore._SIBLING_BOOKS``).
    """
    from datasets.sports_data.offshore import _sibling_entry

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
