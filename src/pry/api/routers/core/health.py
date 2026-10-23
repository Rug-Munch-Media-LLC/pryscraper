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

Logging (2026-10-23): probe bodies moved to ``probe_checks``. They emit ONE
line per state change and never a traceback — the old ``exc_info=True`` on an
unreachable Ollama produced 61 tracebacks / 10 min (80% of log bytes) and hid
every real scrape failure behind probe noise.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from pry.api.routers.core.health_probes import bounded, queue_depth, uptime_seconds
from pry.api.routers.core.probe_checks import (
    probe_database as _check_database,
    probe_flaresolverr as _check_flaresolverr,
    probe_ollama as _check_ollama,
    probe_redis as _check_redis,
)
from pry.core.settings import settings

router = APIRouter(tags=["Health"])

APP_VERSION = settings.app_version


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
        bounded(_check_redis(), "redis"),
        bounded(_check_database(), "database"),
        bounded(_check_flaresolverr(), "flaresolverr", optional=True),
        bounded(_check_ollama(), "ollama", optional=True),
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
    db_ok, redis_ok = await asyncio.gather(
        bounded(_check_database(), "database"),
        bounded(_check_redis(), "redis"),
    )
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
