"""Line-move and arbitrage alerts — deduped, with optional JSON persistence.

The "money printer" needs to scream when the market moves: this module lets a
bot register alerts on an event (``set_alert``), then poll the live odds once
per cycle (``check_alerts``) and receive only the *new* signals.

Alert types: ``market="h2h"`` — line-move alert (fires when either side
moves by at least ``threshold`` percent relative to the baseline line);
``market="arb"`` — arbitrage alert (fires when the best two-way arb yield
clears ``threshold`` percent).

Dedup: alerts fire at most once per *episode* — a signal must fall back
below half its threshold before the same signal can fire again, so a
sustained move does not spam notifications.

Persistence: alerts live in memory by default. When ``PRY_ALERTS_JSON``
points at a file, every mutation is persisted atomically and reloaded at
import time, so alerts survive bot restarts. All file I/O is best-effort.

Contract: :func:`set_alert` / :func:`check_alerts` / :func:`list_alerts` /
:func:`clear_alert` — async, never raises. Internals live in the
``alerts_common`` / ``alerts_fetchers`` / ``alerts_rules`` siblings; this
module re-exports them so the ``sports_data.alerts`` surface is unchanged.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.sports_data.alerts_common import (  # re-exported surface
    _ALERTS as _ALERTS,
    _ALERTS_JSON_ENV as _ALERTS_JSON_ENV,
    _EPISODE_RESET as _EPISODE_RESET,
    _HEADERS as _HEADERS,
    _LOCK as _LOCK,
    _NOTIFY_TIMEOUT as _NOTIFY_TIMEOUT,
    _alerts_path as _alerts_path,
    _best_line as _best_line,
    _comparison_lines as _comparison_lines,
    _line_move as _line_move,
    _load_alerts as _load_alerts,
    _now_iso as _now_iso,
    _persist as _persist,
    _reset_alerts as _reset_alerts,
    _teams_from_label as _teams_from_label,
    _to_float as _to_float,
)
from datasets.sports_data.alerts_fetchers import (  # re-exported surface
    _arb_edge as _arb_edge,
    _current_line as _current_line,
    _load_event_odds as _load_event_odds,
    _notify as _notify,
)
from datasets.sports_data.alerts_rules import (  # re-exported surface
    _evaluate_alert as _evaluate_alert,
    check_alerts as check_alerts,
    clear_alert as clear_alert,
    list_alerts as list_alerts,
    set_alert as set_alert,
)

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported. Kept here (not in a sibling)
# so tests can monkeypatch ``alerts._get_event_odds``.
try:
    from datasets.sports_data.odds import get_event_odds as _get_event_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_event_odds = None  # type: ignore[assignment]

__all__ = [
    "check_alerts",
    "clear_alert",
    "list_alerts",
    "set_alert",
]
