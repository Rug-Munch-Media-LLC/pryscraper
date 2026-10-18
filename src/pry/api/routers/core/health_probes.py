# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Health probe helpers — bounded probes, uptime, and queue depth.

Split out of the health router so the endpoint payload stays readable and the
probe budget lives in one place. Nothing here raises: a failed probe is a
reported state, never an exception on the health path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Every dependency check must finish inside this window so a hung dependency
# cannot stretch /health past its 1s SLO.
PROBE_TIMEOUT_S = 0.8
STARTED_AT = time.monotonic()


def uptime_seconds() -> float:
    """Seconds since this module was imported (process start proxy)."""
    return round(max(0.0, time.monotonic() - STARTED_AT), 1)


def queue_depth() -> int | None:
    """Pending/running jobs in the in-process queue (None when unavailable).

    Reads the local LRU only — no Redis round-trip, so /health stays cheap.
    Job bodies are never returned, so nothing sensitive can leak.
    """
    try:
        from pry.core.deps import queue

        jobs = getattr(queue, "_local_jobs", None)
        if not isinstance(jobs, dict):
            return None
        return sum(
            1
            for job in list(jobs.values())
            if isinstance(job, dict) and job.get("status") in ("pending", "running")
        )
    except Exception:  # noqa: BLE001 — depth is informational, never fatal
        logger.debug("health_queue_depth_unavailable")
        return None


async def bounded(coro: Any) -> bool:
    """Run one dependency probe under the shared timeout budget."""
    try:
        return bool(await asyncio.wait_for(coro, timeout=PROBE_TIMEOUT_S))
    except TimeoutError:
        logger.warning("health_probe_timeout")
        return False


__all__ = ["PROBE_TIMEOUT_S", "bounded", "queue_depth", "uptime_seconds"]
