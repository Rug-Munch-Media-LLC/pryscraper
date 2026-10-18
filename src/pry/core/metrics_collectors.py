# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Prometheus collectors and metric-summary helpers.

Split out of ``pry.core.observability`` (which re-exports these names).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from prometheus_client.core import GaugeMetricFamily

from pry.core.metrics_defs import (
    ACTIVE_CONNECTIONS,
    ACTIVE_SESSIONS,
    CACHE_HITS,
    ERROR_COUNT,
    LLM_CALLS,
    LLM_COST,
    REQUEST_COUNT,
    SCRAPE_COUNT,
    TEMPLATE_USAGE,
)

logger = logging.getLogger(__name__)

# Batch-queue SLIs. A plain Gauge would emit nothing until a caller set it —
# and there is no such caller, so the panel would exist but never fill. A
# collector instead samples the in-process queue at scrape time: always
# fresh, no background thread, no Redis round-trip.
QUEUE_DEPTH_NAME = "pry_queue_depth"
QUEUE_OLDEST_JOB_AGE_NAME = "pry_queue_oldest_job_age_seconds"


class JobQueueCollector:
    """Emit batch-queue depth and oldest-job age from ``deps.queue``.

    Reads only the local LRU (same source as ``/health``'s ``queue_depth``),
    so it never blocks a scrape on Redis. Structural errors degrade to no
    series rather than a fabricated zero: a missing queue means "unknown",
    not "empty".
    """

    def collect(self):  # type: ignore[no-untyped-def]
        depth = GaugeMetricFamily(
            QUEUE_DEPTH_NAME, "Batch jobs pending or running (local queue)", labels=["source"]
        )
        age = GaugeMetricFamily(
            QUEUE_OLDEST_JOB_AGE_NAME,
            "Age in seconds of the oldest pending/running batch job",
            labels=["source"],
        )
        try:
            from pry.core.deps import queue

            jobs = getattr(queue, "_local_jobs", None)
            if not isinstance(jobs, dict):
                return
            active = [
                j
                for j in list(jobs.values())
                if isinstance(j, dict) and j.get("status") in ("pending", "running")
            ]
            depth.add_metric(["local"], len(active))
            oldest = 0.0
            for job in active:
                oldest = max(oldest, _job_age(job))
            age.add_metric(["local"], oldest)
        except Exception:  # noqa: BLE001 — metrics must never break a scrape
            logger.debug("queue_metrics_unavailable")
            return
        yield depth
        yield age


def _job_age(job: dict[str, Any]) -> float:
    """Seconds since ``job['created_at']``; 0.0 when it is unparseable."""
    try:
        created = job.get("created_at")
        ts = time.time()
        if created:
            ts = datetime.fromisoformat(str(created)).timestamp()
        return max(0.0, time.time() - ts)
    except (TypeError, ValueError):
        return 0.0


try:
    REGISTRY.register(JobQueueCollector())
except (ValueError, TypeError):  # pragma: no cover — already registered
    logger.debug("queue_collector_already_registered")


# Only these structural errors degrade a metric read to 0; anything else
# propagates so a broken read is never mistaken for a real zero counter.
_SAMPLE_ERRORS = (AttributeError, IndexError, TypeError, ValueError)


def _sample(name: str, metric: Any) -> int:
    """Best-effort read of a counter/gauge's total value from its samples.

    Excludes the synthetic ``<name>_created`` sample prometheus_client
    adds to counters (its value is a Unix timestamp, not a count).

    Structural errors degrade to 0 (see _SAMPLE_ERRORS); anything else
    propagates, because a failure rendered as 0 is indistinguishable from
    "the counter really is zero" — a false all-clear for operator-facing
    request/error totals, and a bogus derived error_rate_pct.
    """
    if metric is None:
        return 0
    try:
        return int(
            sum(s.value for s in metric.collect()[0].samples if not s.name.endswith("_created"))
        )
    except _SAMPLE_ERRORS:
        logger.warning("observability_exception_handler", exc_info=True)
        return 0


def metrics_summary() -> dict[str, Any]:
    """Return a dict of key counters for a human-facing /metrics summary."""
    return {
        "requests_total": _sample("pry_requests_total", REQUEST_COUNT),
        "request_errors_total": _sample("pry_request_errors_total", ERROR_COUNT),
        "error_rate_pct": (
            round(
                100.0
                * _sample("pry_request_errors_total", ERROR_COUNT)
                / max(1, _sample("pry_requests_total", REQUEST_COUNT)),
                2,
            )
        ),
        "active_sessions": _sample("pry_active_sessions", ACTIVE_SESSIONS),
        "active_connections": _sample("pry_active_connections", ACTIVE_CONNECTIONS),
        "scrapes_total": _sample("pry_scrapes_total", SCRAPE_COUNT),
        "llm_calls_total": _sample("pry_llm_calls_total", LLM_CALLS),
        "llm_cost_usd_total": _sample("pry_llm_cost_usd_total", LLM_COST),
        "cache_hits_total": _sample("pry_cache_hits_total", CACHE_HITS),
        "template_usage_total": _sample("pry_template_usage_total", TEMPLATE_USAGE),
    }


def metrics_summary_text() -> str:
    """Plain-text summary of key counters (for /metrics/summary or logs)."""
    data = metrics_summary()
    lines = ["pry metrics summary"]
    for key, value in data.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def get_metrics_output() -> tuple[bytes, str]:
    """Return Prometheus metrics in text format."""
    return generate_latest(), CONTENT_TYPE_LATEST
