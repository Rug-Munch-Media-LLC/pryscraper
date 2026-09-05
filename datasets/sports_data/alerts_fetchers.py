"""Odds fetchers + webhook notifier for sports alerts.

Split out of ``alerts.py`` (god-file reduction). The ``alerts.py`` facade
re-exports everything here so the surface is unchanged.

``_load_event_odds`` resolves ``_get_event_odds`` through the
``sports_data.alerts`` module at call time so tests that monkeypatch
``alerts._get_event_odds`` keep working.

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
from typing import Any

import httpx

from datasets.sports_data.alerts_common import (
    _HEADERS,
    _NOTIFY_TIMEOUT,
    _best_line,
    _comparison_lines,
    _to_float,
)

logger = logging.getLogger(__name__)


async def _load_event_odds(event_id: str) -> dict[str, Any]:
    """Fetch the live multi-sportsbook comparison (never raises)."""
    from datasets.sports_data import alerts as _alerts_mod

    fn = getattr(_alerts_mod, "_get_event_odds", None)
    if fn is None:
        return {}
    try:
        return await fn(event_id)
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
