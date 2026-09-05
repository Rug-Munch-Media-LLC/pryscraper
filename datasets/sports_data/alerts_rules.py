"""Alert evaluation rules + public API for sports alerts.

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

import logging
import uuid
from typing import Any

from datasets.sports_data.alerts_common import (
    _ALERTS,
    _EPISODE_RESET,
    _LOCK,
    _line_move,
    _now_iso,
    _persist,
    _to_float,
)
from datasets.sports_data.alerts_fetchers import _arb_edge, _current_line, _notify

logger = logging.getLogger(__name__)


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
