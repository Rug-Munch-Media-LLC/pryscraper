"""Anomaly detection rules for extracted-data quality.

Split out of ``pry.engine.quality`` so each detector is a focused, testable
step instead of clauses inside one long function. ``detect_anomalies`` in
``quality`` remains the public entry point and delegates here.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import difflib
from typing import Any

_CONTENT_DRIFT_MIN_LEN = 20
_CONTENT_DRIFT_MAX_RATIO = 0.5


def missing_field_anomalies(
    previous: dict[str, Any], current: dict[str, Any]
) -> list[dict[str, Any]]:
    """Fields present before but absent now -> high severity."""
    return [
        {
            "type": "missing_field",
            "severity": "high",
            "field": field,
            "message": f"Field '{field}' was present in previous extraction but is now missing",
        }
        for field in sorted(set(previous) - set(current))
    ]


def new_field_anomalies(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    """Fields absent before but present now -> info severity."""
    return [
        {
            "type": "new_field",
            "severity": "info",
            "field": field,
            "message": f"New field '{field}' appeared",
        }
        for field in sorted(set(current) - set(previous))
    ]


def type_change_anomaly(field: str, prev_val: Any, curr_val: Any) -> dict[str, Any] | None:
    """Return a type-change anomaly, or None when the types match/are unknown."""
    if prev_val is None or curr_val is None or type(prev_val) is type(curr_val):
        return None
    return {
        "type": "type_change",
        "severity": "high",
        "field": field,
        "message": f"Field '{field}' changed type: {type(prev_val).__name__} → {type(curr_val).__name__}",
        "previous_type": type(prev_val).__name__,
        "current_type": type(curr_val).__name__,
    }


def value_swing_anomaly(
    field: str, prev_val: Any, curr_val: Any, z_score_threshold: float
) -> dict[str, Any] | None:
    """Return a numeric value-swing anomaly, or None when not applicable."""
    if not (isinstance(prev_val, (int, float)) and isinstance(curr_val, (int, float))):
        return None
    if isinstance(prev_val, bool) or isinstance(curr_val, bool):
        return None
    if prev_val == 0:
        return None
    z_score = abs((curr_val - prev_val) / max(abs(prev_val), 0.01))
    if z_score <= z_score_threshold:
        return None
    pct = ((curr_val - prev_val) / abs(prev_val)) * 100
    return {
        "type": "value_swing",
        "severity": "high" if abs(pct) > 50 else "medium",
        "field": field,
        "message": f"Field '{field}' changed by {pct:+.1f}% ({prev_val} → {curr_val})",
        "previous_value": prev_val,
        "current_value": curr_val,
        "change_pct": round(pct, 1),
    }


def content_drift_anomaly(field: str, prev_val: Any, curr_val: Any) -> dict[str, Any] | None:
    """Return a long-text content-drift anomaly, or None when not applicable."""
    if not (isinstance(prev_val, str) and isinstance(curr_val, str)):
        return None
    if prev_val == curr_val or len(prev_val) <= _CONTENT_DRIFT_MIN_LEN:
        return None
    ratio = difflib.SequenceMatcher(None, prev_val, curr_val).ratio()
    if ratio >= _CONTENT_DRIFT_MAX_RATIO:
        return None
    return {
        "type": "content_drift",
        "severity": "medium",
        "field": field,
        "message": f"Field '{field}' content changed significantly ({round(ratio * 100)}% similarity)",
        "similarity": round(ratio, 3),
    }


def common_field_anomalies(
    previous: dict[str, Any], current: dict[str, Any], z_score_threshold: float
) -> list[dict[str, Any]]:
    """Per-field anomalies across fields shared by both extractions."""
    found: list[dict[str, Any]] = []
    for field in sorted(set(previous) & set(current)):
        prev_val = previous[field]
        curr_val = current[field]
        change = type_change_anomaly(field, prev_val, curr_val)
        if change is not None:
            found.append(change)
            continue
        swing = value_swing_anomaly(field, prev_val, curr_val, z_score_threshold)
        if swing is not None:
            found.append(swing)
        drift = content_drift_anomaly(field, prev_val, curr_val)
        if drift is not None:
            found.append(drift)
    return found
