"""Pry — Fallback telemetry recorder.

Makes intelligent-fallback decisions observable: which tiers were tried,
which failed and why, and which tier won. Records are held in a bounded,
thread-safe in-memory ring buffer and optionally appended to a JSONL file
(best-effort — persistence failures are logged, never raised).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pry.core.paths import subdir

logger = logging.getLogger(__name__)

#: Ring-buffer capacity — memory stays bounded regardless of scrape volume.
DEFAULT_RING_SIZE = 500
_DEFAULT_JSONL_NAME = "fallback_telemetry.jsonl"
_TOP_N = 10
_SNAPSHOT_RECENT_LIMIT = 100

# Expected shape for each entry in ``attempts``:
#     {"tier": str, "success": bool, "error": str | None, "duration_ms": float}


@dataclass(slots=True)
class FallbackRecord:
    """One scrape attempt's full fallback journey."""

    domain: str
    tier_order: list[str]
    attempts: list[dict[str, Any]]
    final_tier: str | None
    success: bool
    duration_ms: float
    error: str | None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Plain-JSON-safe copy (deep enough for serialization)."""
        return {
            "domain": self.domain,
            "tier_order": list(self.tier_order),
            "attempts": [dict(attempt) for attempt in self.attempts],
            "final_tier": self.final_tier,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "timestamp": self.timestamp,
        }


_lock = threading.RLock()
_records: deque[FallbackRecord] = deque(maxlen=DEFAULT_RING_SIZE)
_jsonl_enabled = True
_jsonl_path: Path | None = None
_jsonl_default_path: Path | None = None


def set_jsonl_enabled(enabled: bool) -> None:
    """Toggle best-effort JSONL persistence (default on)."""
    global _jsonl_enabled
    with _lock:
        _jsonl_enabled = enabled


def set_jsonl_path(path: Path | str | None) -> None:
    """Override the JSONL log location. ``None`` restores the default path."""
    global _jsonl_path
    with _lock:
        _jsonl_path = Path(path) if path is not None else None


def _resolve_jsonl_path() -> Path:
    global _jsonl_default_path
    if _jsonl_path is not None:
        return _jsonl_path
    if _jsonl_default_path is None:
        _jsonl_default_path = subdir("telemetry") / _DEFAULT_JSONL_NAME
    return _jsonl_default_path


def record_fallback(
    domain: str,
    tier_order: list[str],
    attempts: list[dict[str, Any]],
    final_tier: str | None,
    success: bool,
    duration_ms: float,
    error: str | None,
) -> None:
    """Record one scrape attempt's fallback journey.

    Args:
        domain: Hostname being scraped (e.g. ``example.com``).
        tier_order: Ordered list of tier names considered, cheapest first.
        attempts: One dict per tier attempt; see module docstring for shape.
        final_tier: Tier that ultimately won, or ``None`` on total failure.
        success: Whether the scrape overall succeeded.
        duration_ms: Total fallback-chain duration in milliseconds.
        error: Top-level error message, or ``None`` on success.
    """
    record = FallbackRecord(
        domain=domain,
        tier_order=list(tier_order),
        attempts=[dict(attempt) for attempt in attempts],
        final_tier=final_tier,
        success=bool(success),
        duration_ms=float(duration_ms),
        error=error,
    )
    with _lock:
        _records.append(record)
        if _jsonl_enabled:
            _append_jsonl_locked(record)


def _append_jsonl_locked(record: FallbackRecord) -> None:
    try:
        path = _resolve_jsonl_path()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict()) + "\n")
    except (OSError, TypeError, ValueError):
        logger.warning(
            "fallback_telemetry_jsonl_write_failed",
            extra={"domain": record.domain},
            exc_info=True,
        )


def get_domain_stats(domain: str) -> dict[str, Any]:
    """Per-domain fallback statistics over retained records.

    Includes per-tier success rates + latency, overall success rate,
    average duration, the most common failure reason, and winning tiers.
    """
    with _lock:
        records = [record for record in _records if record.domain == domain]
    return _domain_stats_from(domain, records)


def _domain_stats_from(domain: str, records: list[FallbackRecord]) -> dict[str, Any]:
    total = len(records)
    successes = sum(1 for record in records if record.success)
    durations = [record.duration_ms for record in records]

    tier_attempts: Counter[str] = Counter()
    tier_successes: Counter[str] = Counter()
    tier_durations: dict[str, list[float]] = {}
    failure_reasons: Counter[str] = Counter()
    winning_tiers: Counter[str] = Counter()

    for record in records:
        if record.success and record.final_tier:
            winning_tiers[record.final_tier] += 1
        for attempt in record.attempts:
            tier = str(attempt.get("tier", "unknown"))
            tier_attempts[tier] += 1
            tier_durations.setdefault(tier, []).append(float(attempt.get("duration_ms", 0.0)))
            if attempt.get("success"):
                tier_successes[tier] += 1
            elif attempt.get("error"):
                failure_reasons[str(attempt["error"])] += 1

    tier_stats: dict[str, dict[str, Any]] = {}
    for tier in tier_attempts:
        attempts = tier_attempts[tier]
        successes_for_tier = tier_successes[tier]
        latencies = tier_durations.get(tier, [0.0])
        tier_stats[tier] = {
            "attempts": attempts,
            "successes": successes_for_tier,
            "success_rate": round(successes_for_tier / attempts, 4) if attempts else 0.0,
            "avg_duration_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        }

    most_common = failure_reasons.most_common(1)
    most_common_failure_reason = (
        {"reason": most_common[0][0], "count": most_common[0][1]} if most_common else None
    )

    return {
        "domain": domain,
        "records": total,
        "successes": successes,
        "failures": total - successes,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
        "tier_stats": tier_stats,
        "most_common_failure_reason": most_common_failure_reason,
        "winning_tiers": dict(winning_tiers.most_common()),
    }


def get_global_stats() -> dict[str, Any]:
    """Aggregate fallback statistics across all retained records."""
    with _lock:
        records = list(_records)
    return _global_stats_from(records)


def _global_stats_from(records: list[FallbackRecord]) -> dict[str, Any]:
    total = len(records)
    successes = sum(1 for record in records if record.success)
    durations = [record.duration_ms for record in records]
    winning_tiers: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    tiers_per_success: list[int] = []

    for record in records:
        if record.success:
            tiers_per_success.append(len(record.attempts))
            if record.final_tier:
                winning_tiers[record.final_tier] += 1
        for attempt in record.attempts:
            if not attempt.get("success") and attempt.get("error"):
                failure_reasons[str(attempt["error"])] += 1

    return {
        "records": total,
        "domains": len({record.domain for record in records}),
        "successes": successes,
        "failures": total - successes,
        "overall_success_rate": round(successes / total, 4) if total else 0.0,
        "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
        "avg_tiers_per_success": (
            round(sum(tiers_per_success) / len(tiers_per_success), 2) if tiers_per_success else 0.0
        ),
        "top_winning_tiers": [
            {"tier": tier, "wins": count} for tier, count in winning_tiers.most_common(_TOP_N)
        ],
        "top_failure_reasons": [
            {"reason": reason, "count": count}
            for reason, count in failure_reasons.most_common(_TOP_N)
        ],
    }


def snapshot(recent_limit: int = _SNAPSHOT_RECENT_LIMIT) -> dict[str, Any]:
    """Point-in-time view for the diagnostics endpoint (bounded payload).

    ``recent_limit`` caps how many raw records are embedded so the endpoint
    payload stays small; pass a larger value to inspect deeper history.
    """
    with _lock:
        records = list(_records)
        enabled = _jsonl_enabled
        path_override = _jsonl_path is not None

    recent = records[-recent_limit:] if recent_limit > 0 else []

    domain_summary: dict[str, dict[str, Any]] = {}
    for record in records:
        summary = domain_summary.setdefault(
            record.domain, {"records": 0, "successes": 0, "success_rate": 0.0}
        )
        summary["records"] += 1
        if record.success:
            summary["successes"] += 1
    for summary in domain_summary.values():
        summary["success_rate"] = (
            round(summary["successes"] / summary["records"], 4) if summary["records"] else 0.0
        )

    return {
        "enabled": enabled,
        "jsonl_path_override": path_override,
        "ring": {"capacity": _records.maxlen, "retained": len(records)},
        "global": _global_stats_from(records),
        "domain_summary": domain_summary,
        "recent_records": [record.to_dict() for record in recent],
    }


def reset() -> None:
    """Clear all retained records (test/ops utility)."""
    with _lock:
        _records.clear()
