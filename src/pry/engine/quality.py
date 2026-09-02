"""Pry — Data Quality SLA Dashboard.
Per-extraction quality metrics, anomaly detection, freshness tracking."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import difflib
import hashlib
import json
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

QUALITY_DIR = PRY_DATA_DIR / "quality"
QUALITY_DIR.mkdir(parents=True, exist_ok=True)

# ── Quality Metrics ──


def compute_completeness(
    data: dict[str, Any] | list[Any], schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compute completeness metrics for extracted data.

    Measures:
    - Field presence: what % of expected fields have non-null values
    - Record count: expected vs actual for list data
    - Schema adherence: what % of fields match expected types
    """
    if isinstance(data, list):
        return _compute_list_completeness(data, schema)
    return _compute_dict_completeness(data, schema)


def _compute_dict_completeness(
    data: dict[str, Any], schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compute completeness for a single dict."""
    if not data:
        return {
            "score": 0,
            "total_fields": 0,
            "filled_fields": 0,
            "null_fields": 0,
            "empty_fields": 0,
        }

    total = len(data)
    filled = sum(1 for v in data.values() if v not in (None, "", [], {}))
    nulls = sum(1 for v in data.values() if v is None)
    empties = sum(1 for v in data.values() if v in ("", [], {}) and v is not None)

    score = round(filled / total * 100, 1) if total > 0 else 0.0

    return {
        "score": score,
        "total_fields": total,
        "filled_fields": filled,
        "null_fields": nulls,
        "empty_fields": empties,
    }


def _compute_list_completeness(
    data: list[Any], schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compute completeness for a list of records."""
    if not data:
        return {"score": 0, "record_count": 0, "avg_record_score": 0}

    record_scores = []
    total_possible = 0
    total_filled = 0

    for record in data:
        if isinstance(record, dict):
            result = _compute_dict_completeness(record, schema)
            record_scores.append(result["score"])
            total_possible += result["total_fields"]
            total_filled += result["filled_fields"]

    avg_record = round(sum(record_scores) / len(record_scores), 1) if record_scores else 0.0
    overall = round(total_filled / total_possible * 100, 1) if total_possible > 0 else 0.0

    return {
        "score": overall,
        "record_count": len(data),
        "avg_record_score": avg_record,
        "min_record_score": min(record_scores) if record_scores else 0,
        "max_record_score": max(record_scores) if record_scores else 0,
    }


def compute_schema_adherence(
    data: dict[str, Any] | list[dict[str, Any]],
    expected_types: dict[str, type],
) -> dict[str, Any]:
    """Check if fields match expected types."""
    records = data if isinstance(data, list) else [data]
    field_issues: dict[str, int] = {}
    total_checks = 0
    type_mismatches = 0

    for record in records:
        if isinstance(record, dict):
            for field, expected_type in expected_types.items():
                total_checks += 1
                value = record.get(field)
                if value is not None and not isinstance(value, expected_type):
                    type_mismatches += 1
                    field_issues[field] = field_issues.get(field, 0) + 1

    return {
        "score": round((total_checks - type_mismatches) / total_checks * 100, 1)
        if total_checks > 0
        else 100.0,
        "total_checks": total_checks,
        "type_mismatches": type_mismatches,
        "field_issues": field_issues,
    }


def compute_null_rate(data: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Compute null/empty rate per field."""
    records = data if isinstance(data, list) else [data]
    field_stats: dict[str, dict[str, Any]] = {}

    for record in records:
        if isinstance(record, dict):
            for key, value in record.items():
                if key not in field_stats:
                    field_stats[key] = {"total": 0, "null": 0, "empty": 0}
                field_stats[key]["total"] += 1
                if value is None:
                    field_stats[key]["null"] += 1
                elif value in ("", [], {}):
                    field_stats[key]["empty"] += 1

    return {
        field: {
            "null_rate": round(stats["null"] / stats["total"] * 100, 1),
            "empty_rate": round(stats["empty"] / stats["total"] * 100, 1),
            "total": stats["total"],
        }
        for field, stats in field_stats.items()
    }


def compute_freshness(
    data: dict[str, Any] | list[Any], max_age_seconds: int = 3600
) -> dict[str, Any]:
    """Check data freshness against expected age.

    If ``data`` is a list (or any non-dict), freshness cannot be verified
    from a single timestamp field, so a neutral default is returned rather
    than raising ``AttributeError`` from ``data.get(...)``.
    """
    if not isinstance(data, dict):
        return {
            "fresh": True,
            "age_seconds": None,
            "note": "Data is not a dict — cannot verify freshness",
        }

    now = time.time()
    timestamps = []

    # Look for timestamp fields
    for key in ["timestamp", "checked_at", "cached_at", "scraped_at", "created_at", "updated_at"]:
        val = data.get(key)
        if val:
            timestamps.append(val)

    if not timestamps:
        return {
            "fresh": True,
            "age_seconds": None,
            "note": "No timestamp field found in data — cannot verify freshness",
        }

    # Try to parse the first timestamp
    ts = timestamps[0]
    if isinstance(ts, (int, float)):
        age = now - ts
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
            age = now - dt.timestamp()
        except (ValueError, TypeError):
            return {
                "fresh": True,
                "age_seconds": None,
                "note": f"Could not parse timestamp: {ts[:30]}",
            }
    else:
        return {"fresh": True, "age_seconds": None, "note": "Timestamp in unknown format"}

    return {
        "fresh": age <= max_age_seconds,
        "age_seconds": round(age),
        "max_age_seconds": max_age_seconds,
        "note": f"Data is {_format_age(age)} old",
    }


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def detect_anomalies(
    current_data: dict[str, Any],
    previous_data: dict[str, Any] | None = None,
    z_score_threshold: float = 2.0,
) -> list[dict[str, Any]]:
    """Detect anomalies in extracted data compared to previous runs.

    Flags:
    - Missing fields (field present before, absent now)
    - New fields (field absent before, present now)
    - Value type changes
    - Large value swings (for numeric fields)
    - Empty results when previous had data
    """
    anomalies: list[dict[str, Any]] = []

    if previous_data is None:
        return []

    # Check for empty results
    if not current_data and previous_data:
        anomalies.append(
            {
                "type": "empty_result",
                "severity": "critical",
                "field": "*",
                "message": "Extraction returned empty — previous run had data",
            }
        )
        return anomalies

    if not isinstance(current_data, dict) or not isinstance(previous_data, dict):
        return anomalies

    prev_keys = set(previous_data.keys())
    curr_keys = set(current_data.keys())

    # Missing fields
    missing = prev_keys - curr_keys
    for field in missing:
        anomalies.append(
            {
                "type": "missing_field",
                "severity": "high",
                "field": field,
                "message": f"Field '{field}' was present in previous extraction but is now missing",
            }
        )

    # New fields
    new_fields = curr_keys - prev_keys
    for field in new_fields:
        anomalies.append(
            {
                "type": "new_field",
                "severity": "info",
                "field": field,
                "message": f"New field '{field}' appeared",
            }
        )

    # Value changes for common fields
    common = prev_keys & curr_keys
    for field in common:
        prev_val = previous_data[field]
        curr_val = current_data[field]

        # Type change
        if prev_val is not None and curr_val is not None and type(prev_val) is not type(curr_val):
            anomalies.append(
                {
                    "type": "type_change",
                    "severity": "high",
                    "field": field,
                    "message": f"Field '{field}' changed type: {type(prev_val).__name__} → {type(curr_val).__name__}",
                    "previous_type": type(prev_val).__name__,
                    "current_type": type(curr_val).__name__,
                }
            )
            continue

        # Numeric swing
        if (
            isinstance(prev_val, (int, float))
            and isinstance(curr_val, (int, float))
            and prev_val != 0
        ):
            z_score = abs((curr_val - prev_val) / max(abs(prev_val), 0.01))
            if z_score > z_score_threshold:
                pct = ((curr_val - prev_val) / abs(prev_val)) * 100
                anomalies.append(
                    {
                        "type": "value_swing",
                        "severity": "high" if abs(pct) > 50 else "medium",
                        "field": field,
                        "message": f"Field '{field}' changed by {pct:+.1f}% ({prev_val} → {curr_val})",
                        "previous_value": prev_val,
                        "current_value": curr_val,
                        "change_pct": round(pct, 1),
                    }
                )

        # Text content change
        if (
            isinstance(prev_val, str)
            and isinstance(curr_val, str)
            and prev_val != curr_val
            and len(prev_val) > 20
        ):
            ratio = difflib.SequenceMatcher(None, prev_val, curr_val).ratio()
            if ratio < 0.5:
                anomalies.append(
                    {
                        "type": "content_drift",
                        "severity": "medium",
                        "field": field,
                        "message": f"Field '{field}' content changed significantly ({round(ratio * 100)}% similarity)",
                        "similarity": round(ratio, 3),
                    }
                )

    return anomalies


async def run_quality_check(
    url: str,
    data: dict[str, Any],
    schema: dict[str, Any] | None = None,
    expected_types: dict[str, type] | None = None,
    max_age_seconds: int = 3600,
) -> dict[str, Any]:
    """Run full quality check on extracted data.

    Returns completeness, schema adherence, freshness, anomalies.
    """
    # Load previous data for comparison
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    history_path = QUALITY_DIR / f"{url_hash}.json"
    previous_data: dict[str, Any] | None = None
    if history_path.exists():
        try:
            prev = json.loads(history_path.read_text())
            previous_data = prev.get("data")
        except (json.JSONDecodeError, OSError):
            pass

    # Compute metrics
    completeness = compute_completeness(data, schema)
    freshness = compute_freshness(data, max_age_seconds)
    anomalies = detect_anomalies(data, previous_data)

    null_rate: dict[str, Any] = {}
    schema_adherence: dict[str, Any] = {
        "score": 100.0,
        "total_checks": 0,
        "type_mismatches": 0,
        "field_issues": {},
    }

    if isinstance(data, dict):
        null_rate = compute_null_rate(data)
        if expected_types:
            schema_adherence = compute_schema_adherence(data, expected_types)

    # Save current data for future comparison
    with suppress(OSError):
        history_path.write_text(
            json.dumps({"url": url, "data": data, "checked_at": datetime.now(UTC).isoformat()})
        )

    # Compute overall quality score (weighted average)
    quality_score = round(
        completeness.get("score", 0) * 0.4
        + (100 - len(anomalies) * 10) * 0.3
        + schema_adherence.get("score", 100) * 0.2
        + (100 if freshness.get("fresh") else 50) * 0.1,
        1,
    )
    quality_score = max(0, min(100, quality_score))

    return {
        "url": url,
        "quality_score": quality_score,
        "completeness": completeness,
        "schema_adherence": schema_adherence,
        "freshness": freshness,
        "null_rates": null_rate,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "critical_anomalies": sum(1 for a in anomalies if a["severity"] == "critical"),
        "has_previous_data": previous_data is not None,
        "checked_at": datetime.now(UTC).isoformat(),
    }
