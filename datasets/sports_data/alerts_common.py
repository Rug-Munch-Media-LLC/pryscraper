"""Alert store, persistence, and line-parsing helpers for sports alerts.

Split out of ``alerts.py`` (god-file reduction). The ``alerts.py`` facade
re-exports everything here so the surface is unchanged.

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
import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ALERTS_JSON_ENV = "PRY_ALERTS_JSON"
# Episode reset ratio: a signal must fall below threshold * this before it
# can fire again (dedup hysteresis).
_EPISODE_RESET = 0.5
# Best-effort webhook POST budget.
_NOTIFY_TIMEOUT = httpx.Timeout(3.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

# alert_id -> alert record. Guarded by _LOCK.
_ALERTS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _alerts_path() -> str:
    """Path of the optional JSON persistence file ('' when disabled)."""
    return os.environ.get(_ALERTS_JSON_ENV, "").strip()


def _load_alerts() -> None:
    """Reload alerts from the JSON persistence file.

    A file that cannot be read or parsed leaves the alert store EMPTY, which is
    indistinguishable from "no alerts configured" — the failure is logged.
    """
    path = _alerts_path()
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as handle:
            entries = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("sports_alerts_unreadable", extra={"error": str(exc)[:120]})
        return
    if not isinstance(entries, list):
        logger.warning("sports_alerts_wrong_shape", extra={"path": path[:120]})
        return
    with _LOCK:
        for entry in entries:
            if isinstance(entry, dict) and entry.get("alert_id"):
                _ALERTS[str(entry["alert_id"])] = entry


def _persist() -> None:
    """Write the alert store to the JSON persistence file (best effort)."""
    path = _alerts_path()
    if not path:
        return
    try:
        with _LOCK:
            payload = [dict(alert) for alert in _ALERTS.values()]
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except OSError:
        logger.debug("sports_alerts_persist_failed", exc_info=True)


def _reset_alerts() -> None:
    """Drop all in-memory alerts (tests / ops)."""
    with _LOCK:
        _ALERTS.clear()


def _to_float(value: Any) -> float | None:
    """Coerce a JSON value to float/None ('' / garbage -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _teams_from_label(event_label: str) -> tuple[str | None, str | None]:
    """Extract ``(home, away)`` from the ``"Away @ Home"`` event label."""
    raw = str(event_label or "")
    if " @ " not in raw:
        return None, None
    away, _, home = raw.partition(" @ ")
    return (home.strip() or None), (away.strip() or None)


def _comparison_lines(
    comparison: dict[str, Any],
) -> dict[str, dict[str, float]]:
    """Map a comparison onto ``{book_key: {"home": odds, "away": odds}}``."""
    home_team, away_team = _teams_from_label(str(comparison.get("event") or ""))
    lines: dict[str, dict[str, float]] = {}
    bookmakers = comparison.get("bookmakers")
    if not isinstance(bookmakers, list):
        return lines
    for book in bookmakers:
        if not isinstance(book, dict):
            continue
        book_key = str(book.get("key") or book.get("title") or "").strip().lower()
        if not book_key:
            continue
        prices: dict[str, float] = {}
        markets = book.get("markets")
        if not isinstance(markets, list):
            continue
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            if str(mkt.get("key") or "h2h") != "h2h":
                continue
            by_name: dict[str, float] = {}
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                name = str(outcome.get("name") or "")
                price = _to_float(outcome.get("price"))
                if name and price is not None and price > 1.0:
                    by_name[name] = price
            home = by_name.get(home_team) if home_team else None
            away = by_name.get(away_team) if away_team else None
            if (home is None or away is None) and len(by_name) >= 2:
                names = list(by_name)
                if home is None:
                    home = by_name.get(names[1])
                if away is None:
                    away = by_name.get(names[0])
            if home is not None and away is not None:
                prices = {"home": home, "away": away}
                break
        if prices:
            lines[book_key] = prices
    return lines


def _best_line(lines: dict[str, dict[str, float]]) -> dict[str, float] | None:
    """Best available price per side across books (max decimal odds)."""
    homes = [prices["home"] for prices in lines.values() if prices.get("home") is not None]
    aways = [prices["away"] for prices in lines.values() if prices.get("away") is not None]
    if not homes or not aways:
        return None
    return {"home": max(homes), "away": max(aways)}


def _line_move(baseline: dict[str, Any], line: dict[str, Any]) -> tuple[float, str, str]:
    """Relative % move of the best line vs baseline -> ``(metric, side, dir)``."""
    home_base = _to_float(baseline.get("home")) or 0.0
    away_base = _to_float(baseline.get("away")) or 0.0
    home_cur = _to_float(line.get("home")) or 0.0
    away_cur = _to_float(line.get("away")) or 0.0
    home_move = (home_cur - home_base) / home_base * 100.0 if home_base else 0.0
    away_move = (away_cur - away_base) / away_base * 100.0 if away_base else 0.0
    if abs(home_move) >= abs(away_move):
        side = "home"
        move = home_move
    else:
        side = "away"
        move = away_move
    return abs(move), side, "up" if move >= 0 else "down"
