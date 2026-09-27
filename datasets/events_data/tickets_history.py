"""In-memory price-history store with optional JSON persistence.

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
from typing import Any

from datasets.events_data.tickets_common import _facade, _now_iso, _to_float

logger = logging.getLogger(__name__)

# ── price history store ────────────────────────────────────────────────
# event_id -> ordered snapshots [{date, min_resale, avg_resale, face_value}]
_HISTORY: dict[str, list[dict[str, Any]]] = {}
_LOCK = threading.RLock()

_MAX_HISTORY_PER_EVENT = 200
_HISTORY_JSON_ENV = "PRY_TICKETS_HISTORY_JSON"


# ── price history persistence ──────────────────────────────────────────


def _history_path() -> str:
    """Path of the optional JSON persistence file ('' when disabled)."""
    return os.environ.get(_facade()._HISTORY_JSON_ENV, "").strip()


def _load_history() -> None:
    """Reload tracked price history from the JSON persistence file.

    A file that cannot be read or parsed leaves the in-memory store EMPTY,
    which is indistinguishable from "nothing is tracked". That failure is
    therefore logged rather than swallowed silently.
    """
    path = _history_path()
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as handle:
            entries = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("price_history_unreadable", extra={"error": str(exc)[:120]})
        return
    if not isinstance(entries, dict):
        logger.warning("price_history_wrong_shape", extra={"path": path[:120]})
        return
    max_per_event = _facade()._MAX_HISTORY_PER_EVENT
    with _LOCK:
        for event_id, snapshots in entries.items():
            if not isinstance(snapshots, list):
                continue
            cleaned = [s for s in snapshots if isinstance(s, dict)]
            _HISTORY[str(event_id)] = cleaned[:max_per_event]


def _persist_history() -> None:
    """Write the history store to the JSON persistence file (best effort)."""
    path = _history_path()
    if not path:
        return
    try:
        with _LOCK:
            payload = {event_id: list(snapshots) for event_id, snapshots in _HISTORY.items()}
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except OSError:
        logger.debug("events_history_persist_failed", exc_info=True)


def _reset_history() -> None:
    """Drop all in-memory history (tests / ops)."""
    with _LOCK:
        _HISTORY.clear()


# ── public API ─────────────────────────────────────────────────────────


async def record_price_snapshot(
    event_id: str,
    min_resale: float | None = None,
    avg_resale: float | None = None,
    face_value: float | None = None,
) -> dict[str, Any]:
    """Record one price-history snapshot for an event. Async, never raises.

    Appends ``{date, min_resale, avg_resale, face_value}`` to the tracked
    series (newest last, capped at ``_MAX_HISTORY_PER_EVENT`` per event) and
    persists when ``PRY_TICKETS_HISTORY_JSON`` is set. Returns
    ``{"event_id", "status": "recorded", "count"}``; ``{"status": "error"}``
    for an empty ``event_id``.
    """
    text = (event_id or "").strip()
    if not text:
        return {"event_id": "", "status": "error", "count": 0}
    snapshot = {
        "date": _now_iso(),
        "min_resale": _to_float(min_resale),
        "avg_resale": _to_float(avg_resale),
        "face_value": _to_float(face_value),
    }
    max_per_event = _facade()._MAX_HISTORY_PER_EVENT
    with _LOCK:
        series = _HISTORY.setdefault(text, [])
        series.append(snapshot)
        if len(series) > max_per_event:
            del series[: len(series) - max_per_event]
        count = len(series)
    _persist_history()
    return {"event_id": text, "status": "recorded", "count": count}


async def get_price_history(event_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return tracked price history for an event, newest first. Never raises.

    Returns ``[]`` when nothing has been tracked for the event.
    """
    text = (event_id or "").strip()
    max_per_event = _facade()._MAX_HISTORY_PER_EVENT
    try:
        bounded = max(1, min(int(limit), max_per_event))
    except (TypeError, ValueError):
        bounded = 100
    with _LOCK:
        series = list(_HISTORY.get(text, []))
    return list(reversed(series))[:bounded]
