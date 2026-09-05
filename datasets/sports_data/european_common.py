"""Shared registry, health tracking and status helpers for European books.

Extracted from :mod:`datasets.sports_data.european` — the data-driven book
registry, live availability tracking and the public status helpers. The
per-book fetchers live in :mod:`european_pinnacle`,
:mod:`european_exchange` and :mod:`european_generic`; the aggregate stays
in :mod:`datasets.sports_data.european`.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    from datasets.sports_data.odds import _SPORTS, _resolve_sports
except ImportError:  # pragma: no cover - parallel build guard
    _resolve_sports = None  # type: ignore[assignment]
    _SPORTS = {}  # type: ignore[assignment]

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

# Per-book sport → upstream id maps (data-driven, extracted from code).
_PINNACLE_SPORTS: dict[str, int] = dict(_EUROPEAN_DATA["_PINNACLE_SPORTS"])
_PINNACLE_LEAGUE_KEYWORDS: dict[str, str] = dict(_EUROPEAN_DATA["_PINNACLE_LEAGUE_KEYWORDS"])
_MARATHON_SPORTS: dict[str, str] = dict(_EUROPEAN_DATA["_MARATHON_SPORTS"])
_1XBET_SPORTS: dict[str, int] = dict(_EUROPEAN_DATA["_1XBET_SPORTS"])
_1XBET_LEAGUE_KEYWORDS: dict[str, str] = dict(_EUROPEAN_DATA["_1XBET_LEAGUE_KEYWORDS"])
_BETFAIR_SPORTS: dict[str, str] = dict(_EUROPEAN_DATA["_BETFAIR_SPORTS"])

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


def _status_entry(book: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Registry entry + live availability + optional sibling annotation.

    The sibling lookup is delegated to ``european._sibling_entry`` (kept in
    the facade module so tests can monkeypatch ``european._SIBLING_BOOKS``).
    """
    from datasets.sports_data.european import _sibling_entry

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
