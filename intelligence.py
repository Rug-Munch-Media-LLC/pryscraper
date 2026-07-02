"""Pry — Competitive Intelligence Engine.
Historical snapshots, anomaly detection, natural-language alerts, weekly reports."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import logging
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INTEL_DIR = Path(os.path.expanduser("~/.pry/intel"))
INTEL_DIR.mkdir(parents=True, exist_ok=True)


# ── Historical Snapshots ──


def _snapshot_path(competitor_id: str) -> Path:
    return INTEL_DIR / f"{competitor_id}_snapshots.jsonl"


def record_snapshot(
    competitor_id: str,
    competitor_name: str,
    url: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Record a data snapshot for a competitor.

    Each snapshot is appended to a JSONL file for the competitor.
    """
    snapshot = {
        "ts": datetime.now(UTC).isoformat(),
        "unix_ts": time.time(),
        "competitor_id": competitor_id,
        "competitor_name": competitor_name,
        "url": url,
        "fields": fields,
    }
    path = _snapshot_path(competitor_id)
    try:
        with open(path, "a") as f:
            f.write(json.dumps(snapshot) + "\n")
        logger.info("snapshot_recorded", extra={"competitor": competitor_name})
        return snapshot
    except OSError as e:
        return {"error": str(e)}


def get_snapshots(
    competitor_id: str,
    limit: int = 50,
    since_hours: int | None = None,
) -> list[dict[str, Any]]:
    """Get snapshots for a competitor, most recent first."""
    path = _snapshot_path(competitor_id)
    if not path.exists():
        return []

    snapshots = []
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            snapshots.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        return []

    # Filter by time
    if since_hours:
        cutoff = time.time() - (since_hours * 3600)
        snapshots = [s for s in snapshots if s.get("unix_ts", 0) >= cutoff]

    # Sort by time (newest first) and limit
    snapshots.sort(key=lambda x: x.get("unix_ts", 0), reverse=True)
    return snapshots[:limit]


# ── Anomaly Detection ──


def compute_field_statistics(
    snapshots: list[dict[str, Any]],
    field: str,
) -> dict[str, Any]:
    """Compute statistics for a field across snapshots."""
    values = [s.get("fields", {}).get(field) for s in snapshots]
    values = [v for v in values if v is not None]

    if not values or len(values) < 2:
        return {"count": len(values), "has_history": False}

    numeric_values = [v for v in values if isinstance(v, (int, float))]
    string_values = [str(v) for v in values if isinstance(v, str)]

    result: dict[str, Any] = {
        "count": len(values),
        "has_history": True,
        "field": field,
    }

    if numeric_values:
        result["mean"] = round(statistics.mean(numeric_values), 2)
        result["median"] = round(statistics.median(numeric_values), 2)
        result["min"] = min(numeric_values)
        result["max"] = max(numeric_values)
        if len(numeric_values) > 2:
            result["stdev"] = round(statistics.stdev(numeric_values), 2)
        result["latest"] = numeric_values[-1]
        result["previous"] = numeric_values[-2] if len(numeric_values) >= 2 else None

    if string_values:
        result["unique_values"] = len(set(string_values))
        result["latest"] = string_values[-1]
        result["previous"] = string_values[-2] if len(string_values) >= 2 else None

    return result


def detect_anomalies_numeric(
    current_value: float,
    history: list[float],
    z_score_threshold: float = 2.0,
) -> dict[str, Any]:
    """Detect anomalies in a numeric field using z-score."""
    if len(history) < 3:
        return {"anomaly": False, "reason": "Insufficient history"}

    mean = statistics.mean(history)
    stdev = statistics.stdev(history) if len(history) > 1 else 1.0
    if stdev == 0:
        return {"anomaly": current_value != mean, "reason": "Value changed from constant history"}

    z_score = abs((current_value - mean) / stdev)
    pct_change = ((current_value - mean) / mean) * 100 if mean != 0 else 0

    return {
        "anomaly": z_score >= z_score_threshold,
        "z_score": round(z_score, 2),
        "pct_change": round(pct_change, 1),
        "mean": round(mean, 2),
        "stdev": round(stdev, 2),
        "severity": "high" if z_score >= 3.0 else "medium" if z_score >= 2.0 else "low",
    }


# ── Natural Language Alerts ──


def generate_alert(
    competitor_name: str,
    field: str,
    old_value: Any,
    new_value: Any,
    anomaly_info: dict[str, Any] | None = None,
) -> str:
    """Generate a natural-language alert for a detected change."""
    intro = f"*{competitor_name}*"
    if isinstance(new_value, (int, float)) and isinstance(old_value, (int, float)):
        pct = ((new_value - old_value) / old_value) * 100 if old_value != 0 else 0
        direction = "increased" if pct > 0 else "decreased"
        change_part = f"{direction} {field} from {old_value} to {new_value} ({abs(pct):.1f}%)"
    elif isinstance(new_value, str) and isinstance(old_value, str):
        if len(new_value) > 50 or len(old_value) > 50:
            change_part = (
                f"changed {field} (length: {len(old_value)} \u2192 {len(new_value)} chars)"
            )
        else:
            change_part = f'changed {field}: "{old_value}" \u2192 "{new_value}"'
    else:
        change_part = f"updated {field}"

    severity = ""
    if anomaly_info and anomaly_info.get("anomaly"):
        severity = " \u26a0\ufe0f *ANOMALY DETECTED*"

    alert = f"{intro} {change_part}{severity}"

    if anomaly_info and anomaly_info.get("z_score"):
        alert += f" (z-score: {anomaly_info['z_score']})"

    if anomaly_info and anomaly_info.get("pct_change"):
        alert += f" \u2014 unusual change of {anomaly_info['pct_change']}% vs historical average"

    return alert


# ── Weekly Reports ──


def generate_weekly_report(
    competitors: list[dict[str, Any]],
    days_back: int = 7,
) -> dict[str, Any]:
    """Generate a weekly competitive intelligence report."""
    cutoff_ts = time.time() - (days_back * 86400)
    report_sections: list[dict[str, Any]] = []

    for comp in competitors:
        comp_id = comp.get("id", comp.get("name", "").lower().replace(" ", "_"))
        comp_name = comp.get("name", "Unknown")
        snapshots = get_snapshots(comp_id)
        weekly = [s for s in snapshots if s.get("unix_ts", 0) >= cutoff_ts]

        if not weekly:
            continue

        # Get fields that changed this week
        if len(weekly) >= 2:
            latest = weekly[0].get("fields", {})
            oldest = weekly[-1].get("fields", {})

            changes = []
            all_fields = set(latest.keys()) | set(oldest.keys())
            for field in all_fields:
                old_val = oldest.get(field)
                new_val = latest.get(field)
                if old_val != new_val:
                    changes.append(
                        {
                            "field": field,
                            "from": old_val,
                            "to": new_val,
                            "alert": generate_alert(comp_name, field, old_val, new_val),
                        }
                    )

            if changes:
                report_sections.append(
                    {
                        "competitor": comp_name,
                        "changes_count": len(changes),
                        "snapshots_this_week": len(weekly),
                        "changes": changes,
                    }
                )

    # Summary
    total_changes = sum(s["changes_count"] for s in report_sections)
    most_active = (
        max(report_sections, key=lambda x: x["changes_count"]) if report_sections else None
    )

    return {
        "report_period": f"Last {days_back} days",
        "generated_at": datetime.now(UTC).isoformat(),
        "competitors_tracked": len(competitors),
        "competitors_with_changes": len(report_sections),
        "total_changes": total_changes,
        "most_active_competitor": most_active["competitor"] if most_active else None,
        "sections": report_sections,
        "summary": _generate_report_summary(report_sections, total_changes, len(competitors)),
    }


def _generate_report_summary(
    sections: list[dict[str, Any]],
    total_changes: int,
    total_competitors: int,
) -> str:
    """Generate a text summary of the weekly report."""
    if not sections:
        return f"No significant changes detected across {total_competitors} tracked competitors."

    most_active = max(sections, key=lambda x: x["changes_count"])
    lines = [
        "Weekly Competitive Intelligence Summary",
        "",
        f"Tracked {total_competitors} competitors over the past 7 days.",
        f"Detected {total_changes} changes across {len(sections)} competitors.",
        "",
        f"Most active: {most_active['competitor']} with {most_active['changes_count']} changes.",
    ]

    for section in sections[:5]:
        lines.append("")
        lines.append(f"\u2500\u2500 {section['competitor']} \u2500\u2500")
        for change in section["changes"][:3]:
            lines.append(f"  \u2022 {change['alert']}")
        if len(section["changes"]) > 3:
            lines.append(f"  ... and {len(section['changes']) - 3} more changes")

    return "\n".join(lines)
