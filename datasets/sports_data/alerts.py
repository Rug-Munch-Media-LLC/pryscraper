"""Line-move and arbitrage alerts — deduped, with optional JSON persistence.

The "money printer" needs to scream when the market moves: this module lets a
bot register alerts on an event (``set_alert``), then poll the live odds once
per cycle (``check_alerts``) and receive only the *new* signals.

Alert types
-----------
* ``market="h2h"`` — line-move alert. Tracks the best available moneyline
  price per side across all books; fires when either side moves by at least
  ``threshold`` percent relative to the alert's baseline line.
* ``market="arb"`` — arbitrage alert. Tracks the best two-way arb yield
  across books; fires when the yield clears ``threshold`` percent.

Dedup
-----
Alerts fire at most once per *episode*: a signal must fall back below half
its threshold before the same signal can fire again, so a sustained move
does not spam notifications (and a fresh move after a pause still fires).

Persistence
-----------
Alerts live in memory by default. When ``PRY_ALERTS_JSON`` points at a file,
every mutation (set / clear / trigger bookkeeping) is persisted atomically
and reloaded at import time, so alerts survive bot restarts. All file I/O is
best-effort and never raises.

Contract
--------
* :func:`set_alert` — async, never raises, returns ``{"alert_id", "status"}``
  (``"active"`` on success, ``"error"`` on invalid input).
* :func:`check_alerts` — async, never raises, returns the list of fired
  alert events for this cycle (``[]`` when nothing fired).
* :func:`list_alerts` — async, never raises, returns a snapshot of all
  registered alerts.
* :func:`clear_alert` — async, never raises, returns
  ``{"alert_id", "status": "cleared" | "not_found"}``.

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
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported.
try:
    from datasets.sports_data.odds import get_event_odds as _get_event_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_event_odds = None  # type: ignore[assignment]

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
    """Reload alerts from the JSON persistence file (best effort)."""
    path = _alerts_path()
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as handle:
            entries = json.load(handle)
    except (OSError, ValueError):
        return
    if not isinstance(entries, list):
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


_load_alerts()


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


async def _load_event_odds(event_id: str) -> dict[str, Any]:
    """Fetch the live multi-sportsbook comparison (never raises)."""
    if _get_event_odds is None:
        return {}
    try:
        return await _get_event_odds(event_id)
    except Exception:
        logger.exception("sports_alerts_odds_failed", extra={"event_id": event_id})
        return {}


async def _current_line(event_id: str) -> dict[str, float] | None:
    """Best available h2h line for the event, or ``None``."""
    comparison = await _load_event_odds(event_id)
    if not comparison:
        return None
    return _best_line(_comparison_lines(comparison))


async def _arb_edge(event_id: str) -> float | None:
    """Best two-way arb yield (percent) for the event, or ``None``.

    Uses :func:`sports_data.arbitrage.detect_2way_arb` on the best price per
    side. Imported lazily so this module loads even when a parallel agent
    has not finished writing ``sports_data.arbitrage`` yet.
    """
    comparison = await _load_event_odds(event_id)
    if not comparison:
        return None
    best = _best_line(_comparison_lines(comparison))
    if not best:
        return None
    try:
        from datasets.sports_data.arbitrage import detect_2way_arb
    except ImportError:  # pragma: no cover - parallel build guard
        return None
    result = detect_2way_arb(
        {"book": "best_home", "odds": best["home"]},
        {"book": "best_away", "odds": best["away"]},
    )
    if not result:
        return None
    edge = _to_float(result.get("arb_yield_pct"))
    return edge if edge is not None and edge > 0 else None


async def _evaluate_alert(alert: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Check one alert; return ``(fired_event, store_updates)``.

    ``store_updates`` is applied to the stored alert after evaluation (or on
    fire). A ``None`` event means nothing fired this cycle.
    """
    market = str(alert.get("market") or "h2h")
    threshold = _to_float(alert.get("threshold")) or 0.0
    event_id = str(alert.get("event_id") or "")
    if market == "h2h":
        line = await _current_line(event_id)
        if not line:
            return None, {}
        baseline = alert.get("baseline")
        if (
            not isinstance(baseline, dict)
            or baseline.get("home") is None
            or baseline.get("away") is None
        ):
            # No reference point yet — establish the baseline this cycle.
            return None, {"baseline": line}
        metric, side, direction = _line_move(baseline, line)
        signal_key = f"line_move:{side}:{direction}"
        fire = metric >= threshold and alert.get("last_signal_key") != signal_key
        reset = metric < threshold * _EPISODE_RESET
        updates: dict[str, Any] = {"last_edge": round(metric, 2), "last_line": line}
        if reset:
            updates["last_signal_key"] = None
        if not fire:
            return None, updates
        updates["last_signal_key"] = signal_key
        return (
            {
                "alert_id": alert.get("alert_id"),
                "event_id": event_id,
                "market": market,
                "kind": "line_move",
                "signal_key": signal_key,
                "edge": round(metric, 2),
                "message": (
                    f"{side} line moved {direction} {metric:.2f}% (threshold {threshold:.2f}%)"
                ),
                "detail": {
                    "baseline": baseline,
                    "line": line,
                    "move_pct": round(metric, 2),
                    "side": side,
                    "direction": direction,
                },
                "at": _now_iso(),
            },
            updates,
        )
    edge = await _arb_edge(event_id)
    if edge is None:
        return None, {}
    signal_key = f"arb:{round(edge, 2)}"
    fire = edge >= threshold and alert.get("last_signal_key") != signal_key
    reset = edge < threshold * _EPISODE_RESET
    updates = {"last_edge": round(edge, 2)}
    if reset:
        updates["last_signal_key"] = None
    if not fire:
        return None, updates
    updates["last_signal_key"] = signal_key
    return (
        {
            "alert_id": alert.get("alert_id"),
            "event_id": event_id,
            "market": market,
            "kind": "arb",
            "signal_key": signal_key,
            "edge": round(edge, 2),
            "message": f"arbitrage edge {edge:.2f}% (threshold {threshold:.2f}%)",
            "detail": {"arb_yield_pct": round(edge, 2)},
            "at": _now_iso(),
        },
        updates,
    )


async def _notify(url: Any, event: dict[str, Any]) -> bool:
    """Fire-and-forget webhook POST of a fired alert (best effort)."""
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=_NOTIFY_TIMEOUT, headers=_HEADERS) as client:
            response = await client.post(str(url), json=event)
            response.raise_for_status()
        return True
    except (httpx.HTTPError, OSError, ValueError):
        logger.debug("sports_alerts_notify_failed", exc_info=True)
        return False


async def set_alert(
    event_id: str,
    market: str = "h2h",
    threshold: float = 2.0,
    notify_url: str | None = None,
) -> dict[str, Any]:
    """Register a line-move or arbitrage alert (never raises).

    Args:
        event_id: Event id to watch.
        market: ``"h2h"`` (line-move, default) or ``"arb"``.
        threshold: Trigger threshold in percent (line-move: relative move;
            arb: yield). Must be > 0.
        notify_url: Optional webhook; fired alerts are POSTed to it.

    Returns:
        ``{"alert_id": <id>, "status": "active"}`` on success, or
        ``{"alert_id": "", "status": "error"}`` on invalid input.
    """
    target_id = str(event_id or "").strip()
    market = str(market or "h2h").strip().lower()
    try:
        threshold_value = float(threshold)
    except (TypeError, ValueError):
        threshold_value = 0.0
    if not target_id or market not in ("h2h", "arb") or threshold_value <= 0:
        return {"alert_id": "", "status": "error"}
    alert_id = uuid.uuid4().hex[:12]
    alert: dict[str, Any] = {
        "alert_id": alert_id,
        "event_id": target_id,
        "market": market,
        "threshold": threshold_value,
        "notify_url": str(notify_url).strip() if notify_url else None,
        "created_at": _now_iso(),
        "last_triggered_at": None,
        "triggered_count": 0,
        "baseline": None,
        "last_signal_key": None,
        "last_edge": 0.0,
    }
    if market == "h2h":
        # Best-effort baseline so the first check can fire immediately when
        # the line has already moved (otherwise the first check establishes it).
        line = await _current_line(target_id)
        if line:
            alert["baseline"] = line
    with _LOCK:
        _ALERTS[alert_id] = alert
    _persist()
    return {"alert_id": alert_id, "status": "active"}


async def check_alerts() -> list[dict[str, Any]]:
    """Evaluate every alert against the live odds (never raises).

    Returns the alerts that fired this cycle (each with ``kind``, ``edge``,
    ``message``, ``detail``, ``at`` and a ``notified`` flag). Deduped per
    episode — see the module docstring.
    """
    with _LOCK:
        snapshot = [dict(alert) for alert in _ALERTS.values()]
    fired: list[dict[str, Any]] = []
    for alert in snapshot:
        try:
            event, updates = await _evaluate_alert(alert)
        except Exception:
            logger.exception(
                "sports_alerts_evaluate_failed", extra={"alert_id": alert.get("alert_id")}
            )
            continue
        if event is not None:
            event["notified"] = await _notify(alert.get("notify_url"), event)
            fired.append(event)
            updates["last_triggered_at"] = event["at"]
            updates["triggered_count"] = int(alert.get("triggered_count") or 0) + 1
        if updates:
            with _LOCK:
                current = _ALERTS.get(str(alert.get("alert_id") or ""))
                if current is not None:
                    current.update(updates)
            _persist()
    return fired


async def list_alerts() -> list[dict[str, Any]]:
    """Return a snapshot of all registered alerts (never raises)."""
    with _LOCK:
        return [dict(alert) for alert in _ALERTS.values()]


async def clear_alert(alert_id: str) -> dict[str, Any]:
    """Remove an alert by id (never raises)."""
    target = str(alert_id or "").strip()
    with _LOCK:
        removed = _ALERTS.pop(target, None)
    if removed is not None:
        _persist()
        return {"alert_id": target, "status": "cleared"}
    return {"alert_id": target, "status": "not_found"}
