# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Dependency probes for ``/health`` — honest timeouts, one-line outcomes.

Split out of ``health.py`` (which sat at its 200-line ceiling) so the route
module stays a thin router and every probe shares one timeout discipline.

Timeout discipline (2026-10-23): the HTTP probes used to pass ``timeout=3``
while the probe budget was 0.8 s.  The client deadline could never fire, so a
hung store was always cancelled by ``asyncio.wait_for`` and reported as "no
result" — indistinguishable from a fast connection error, and the four stores
all carried the same ``latency_ms`` (the shared fan-out wall clock).  Client
deadlines are now *below* the budget, so a failure is classified as a real
``ConnectError`` / ``ReadTimeout`` before the budget cancels it.

No probe raises and none logs a traceback: one line per state change is emitted
by :mod:`pry.api.routers.core.probe_log`.
"""

from __future__ import annotations

import asyncio
import time
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pry.api.routers.core.health_probes import PROBE_TIMEOUT_S
from pry.api.routers.core.probe_log import ProbeFailure, ProbeTiming, probes
from pry.core.client import get_client
from pry.core.settings import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

#: Client-side deadline, deliberately BELOW the probe budget so httpx loses
#: the race predictably and we log the real failure class.
CLIENT_TIMEOUT_S = round(PROBE_TIMEOUT_S * 0.9, 2)


@lru_cache(maxsize=1)
def redis_probe_client() -> Redis:
    """Process-wide probe client — one pool, reused by every health probe.

    A client per probe leaked a pool on every failed ping (the except path
    never closed it) and on every cancelled probe, so a Redis blip turned the
    healthcheck into a client factory.
    """
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.redis_url)


async def _timed(dependency: str, optional: bool, coro: Any) -> bool:
    """Run one probe under the inner deadline; report once; never raise."""
    start = time.monotonic()
    reason: str | None = None
    error_type: str | None = None
    try:
        async with asyncio.timeout(CLIENT_TIMEOUT_S):
            ok = bool(await coro)
        reason = None if ok else "unhealthy"
    except TimeoutError:
        ok, reason, error_type = False, "budget_exhausted", "TimeoutError"
    except Exception as exc:  # noqa: BLE001 — a probe must never fail the route
        ok = False
        reason = str(exc)[:200] or type(exc).__name__
        error_type = type(exc).__name__
    probes.report(
        dependency,
        ok,
        ProbeTiming(
            elapsed_ms=int((time.monotonic() - start) * 1000),
            budget_ms=int(PROBE_TIMEOUT_S * 1000),
        ),
        ProbeFailure(reason=reason or "unhealthy", error_type=error_type, optional=optional),
    )
    return ok


async def _redis_ping() -> bool:
    await redis_probe_client().ping()
    return True


async def _db_available() -> bool:
    from pry.core.db import db_health

    result = await asyncio.to_thread(db_health)
    return bool(result.get("available"))


async def _flaresolverr_ok() -> bool:
    client = await get_client()
    resp = await client.post(
        settings.flaresolverr_url,
        json={"cmd": "sessions.list"},
        headers={"Content-Type": "application/json"},
        timeout=CLIENT_TIMEOUT_S,
    )
    return resp.is_success


async def _ollama_ok() -> bool:
    client = await get_client()
    resp = await client.get(f"{settings.ollama_url}/api/tags", timeout=CLIENT_TIMEOUT_S)
    return resp.is_success


async def probe_redis() -> bool:
    """CRITICAL dep — ping redis over the shared probe client."""
    return await _timed("redis", False, _redis_ping())


async def probe_database() -> bool:
    """CRITICAL dep — SQLAlchemy engine reachable (probe runs in a thread)."""
    return await _timed("database", False, _db_available())


async def probe_flaresolverr() -> bool:
    """OPTIONAL dep — tier 3 of the 9-tier scrape fallback chain."""
    return await _timed("flaresolverr", True, _flaresolverr_ok())


async def probe_ollama() -> bool:
    """OPTIONAL dep — LLM enhancement only; unset URL means "not deployed"."""
    if not settings.ollama_url:
        probes.report(
            "ollama",
            False,
            ProbeTiming(elapsed_ms=0, budget_ms=int(PROBE_TIMEOUT_S * 1000)),
            ProbeFailure(reason="not_configured", optional=True),
        )
        return False
    return await _timed("ollama", True, _ollama_ok())


__all__ = [
    "CLIENT_TIMEOUT_S",
    "probe_database",
    "probe_flaresolverr",
    "probe_ollama",
    "probe_redis",
    "redis_probe_client",
]
