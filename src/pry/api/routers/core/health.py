"""Pry — Health router (liveness, readiness, dependency probes).

Split from api.py. Replaces the inline /health, /live, /ready endpoints.

Endpoints (4):
  GET /healthz   — Pure liveness (always 200 while the process serves)
  GET /health    — Readiness-style summary; 200 unless a CRITICAL dep is down.
                   Optional deps (FlareSolverr, Ollama) are reported
                   informationally and NEVER gate the verdict.
  GET /live      — Kubernetes liveness probe (alias of /healthz)
  GET /ready     — Kubernetes readiness probe (critical deps only)

Dependency tiers (2026-08-25 health-contract fix):
  CRITICAL  — redis (queue/cache backbone), database (via engine import path)
  OPTIONAL  — flaresolverr (tier 3 of 9 scrape fallbacks), ollama (LLM enhance)

Incident context: 2026-08-21..25 pry reported unhealthy for 4 days because
/health gated on FlareSolverr alone. Optional deps must not fail the service.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import TYPE_CHECKING

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from pry.api.client import get_client
from pry.api.routers.core.health_probes import bounded, queue_depth, uptime_seconds
from pry.core.settings import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])

APP_VERSION = settings.app_version


@lru_cache(maxsize=1)
def _redis_probe_client() -> Redis:
    """Process-wide probe client — one pool, reused by every health probe.

    A client per probe leaked a pool on every failed ping (the except path
    never closed it) and on every cancelled probe, so a Redis blip turned the
    healthcheck into a client factory.
    """
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.redis_url)


async def _check_redis() -> bool:
    """CRITICAL dep — ping redis over the shared probe connection."""
    try:
        await _redis_probe_client().ping()
        return True
    except redis.RedisError:
        logger.warning("health_exception_handler", exc_info=True)
        return False


async def _check_database() -> bool:
    """CRITICAL dep — SQLAlchemy engine reachable.

    The sync ``db_health()`` probe is run in a worker thread so it never
    blocks the event loop (ASYNC240). Fails closed (False) on any error.
    """
    try:
        from pry.core.db import db_health

        result = await asyncio.to_thread(db_health)
        return bool(result.get("available"))
    except Exception:
        logger.warning("health_exception_handler", exc_info=True)
        return False


async def _check_flaresolverr() -> bool:
    """OPTIONAL dep — tier 3 of the 9-tier scrape fallback chain."""
    try:
        c = await get_client()
        r = await c.post(
            settings.flaresolverr_url,
            json={"cmd": "sessions.list"},
            headers={"Content-Type": "application/json"},
            timeout=3,
        )
        return r.is_success
    except Exception:
        logger.warning("health_exception_handler", exc_info=True)
        return False


async def _check_ollama() -> bool:
    """OPTIONAL dep — LLM enhancement only."""
    try:
        c = await get_client()
        r = await c.get(f"{settings.ollama_url}/api/tags", timeout=3)
        return r.is_success
    except Exception:
        logger.warning("health_exception_handler", exc_info=True)
        return False


@router.get("/healthz", summary="Pure liveness — always 200 while serving")
async def healthz() -> dict[str, str]:
    """Liveness: the process answers. No dependency probes."""
    return {"status": "ok", "version": APP_VERSION}


@router.get("/health", summary="Health summary — gated by CRITICAL deps only")
async def health_check() -> JSONResponse:
    """Readiness-style health: 200 iff every CRITICAL dependency is up.

    Reports database/redis reachability, redis degradation, queue depth,
    version and uptime. Optional dependencies are informational and never
    gate the verdict. Total probe time is capped at ~0.8s.
    """
    redis_ok, db_ok, flare_ok, ollama_ok = await asyncio.gather(
        bounded(_check_redis()),
        bounded(_check_database()),
        bounded(_check_flaresolverr()),
        bounded(_check_ollama()),
        return_exceptions=False,
    )
    deps = {
        "redis": redis_ok,  # CRITICAL
        "database": db_ok,  # CRITICAL
        "flaresolverr": flare_ok,  # optional — informational
        "ollama": ollama_ok,  # optional — informational
    }
    # BOTH critical deps must be up (redis = queue/cache backbone,
    # database = key issuance/metering/billing). Optional deps never gate.
    healthy = redis_ok and db_ok
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "version": APP_VERSION,
            "uptime_seconds": uptime_seconds(),
            "queue_depth": queue_depth(),
            "dependencies": deps,
            "services": {
                "database": "up" if db_ok else "down",
                "redis": "up" if redis_ok else "degraded",
            },
        },
    )


@router.get("/live", summary="Kubernetes liveness probe")
async def live() -> dict[str, str]:
    """Simple liveness — always returns 200 if the process is running."""
    return {"status": "alive"}


@router.get("/ready", summary="Kubernetes readiness probe", response_model=None)
async def ready() -> JSONResponse | dict[str, str]:
    """Readiness — CRITICAL dependencies only (redis + database).

    NOTE: this deliberately does NOT probe Ollama or FlareSolverr. Both are
    optional enhancement tiers; gating readiness on them caused the
    2026-08-21 four-day false-unhealthy incident.
    """
    db_ok, redis_ok = await asyncio.gather(bounded(_check_database()), bounded(_check_redis()))
    if db_ok and redis_ok:
        return {"status": "ready"}
    return JSONResponse(
        status_code=503,
        content={
            "status": "not_ready",
            "checks": {"database": db_ok, "redis": redis_ok},
        },
    )


@router.get("/version", summary="Service version")
async def version() -> dict[str, str]:
    """Return service version information."""
    return {
        "version": settings.app_version,
        "service": settings.app_name,
        "status": "operational",
    }
