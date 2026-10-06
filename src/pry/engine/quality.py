"""Pry — Data Quality SLA Dashboard.
Per-extraction quality metrics, anomaly detection, freshness tracking."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import hashlib
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

# compute_freshness moved to pry.engine.quality_checks.freshness. Re-exported
# here so the four existing `from pry.engine.quality import compute_freshness`
# call sites keep working unchanged.
from pry.engine.quality_checks.freshness import compute_freshness  # noqa: E402

# detect_anomalies moved to pry.engine.quality_report (detection rules live in
# pry.engine.quality_anomaly_rules). Re-exported so existing import sites keep
# working unchanged.
from pry.engine.quality_report import detect_anomalies  # noqa: E402

__all__ = [
    "QUALITY_DIR",
    "compute_completeness",
    "compute_freshness",
    "compute_null_rate",
    "compute_schema_adherence",
    "detect_anomalies",
    "run_quality_check",
]

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
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("quality_history_load_failed", extra={"error": str(e)[:160]})

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
