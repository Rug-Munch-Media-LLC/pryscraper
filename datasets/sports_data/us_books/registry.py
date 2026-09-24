"""Data-driven US sportsbook registry and availability state."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_json(name: str) -> Any:
    with (_DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _mark(
    book_id: str,
    *,
    ok: bool,
    blocked: bool = False,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Record the outcome of the last fetch attempt for one book."""
    health = _HEALTH.setdefault(
        book_id,
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
    health["last_checked"] = datetime.now(UTC).isoformat()
    if latency_ms is not None:
        health["latency_ms"] = int(latency_ms)
    if error is not None:
        health["error"] = str(error)


def book_status() -> dict[str, Any]:
    """Per-book registry entry merged with live availability.

    Returns a mapping of book id -> ``{id, name, category, odds_url_template,
    method, geo_required, confidence, notes, availability: {reachable,
    blocked, last_checked, latency_ms, error}}``. Never raises.
    """
    return {
        book_id: {"name": entry["name"], **entry, "availability": dict(_HEALTH[book_id])}
        for book_id, entry in US_BOOKS.items()
    }


_US_BOOK_DATA: dict[str, Any] = _load_json("us_books.json")
US_BOOKS: dict[str, dict[str, Any]] = _US_BOOK_DATA["US_BOOKS"]
_US_BOOK_IDS: tuple[str, ...] = tuple(US_BOOKS.keys())
_DK_CATEGORY_IDS: dict[str, int] = _US_BOOK_DATA["_DK_CATEGORY_IDS"]
_FD_EVENT_GROUP_IDS: dict[str, int] = _US_BOOK_DATA["_FD_EVENT_GROUP_IDS"]
_PB_COMPETITION_IDS: dict[str, int] = _US_BOOK_DATA["_PB_COMPETITION_IDS"]
_BR_GROUP_IDS: dict[str, int] = _US_BOOK_DATA["_BR_GROUP_IDS"]
_PB_DETAIL_TEMPLATE = "https://api.pointsbet.com/api/v2/events/{event_key}"
_HEALTH: dict[str, dict[str, Any]] = {
    book_id: {
        "reachable": True,
        "blocked": False,
        "last_checked": None,
        "latency_ms": None,
        "error": None,
    }
    for book_id in _US_BOOK_IDS
}
