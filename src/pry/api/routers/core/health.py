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

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from pry.api.client import get_client
from pry.core.settings import settings

router = APIRouter(tags=["Health"])

APP_VERSION = "3.0.0"


async def _check_redis() -> bool:
    """CRITICAL dep — ping redis."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.close()  # type: ignore[attr-defined]  # redis.asyncio.Redis has close() in older stubs
        return True
    except redis.RedisError:
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
    except Exception:  # noqa: BLE001
        return False


async def _check_ollama() -> bool:
    """OPTIONAL dep — LLM enhancement only."""
    try:
        c = await get_client()
        r = await c.get(f"{settings.ollama_url}/api/tags", timeout=3)
        return r.is_success
    except Exception:  # noqa: BLE001
        return False


@router.get("/healthz", summary="Pure liveness — always 200 while serving")
async def healthz() -> dict[str, str]:
    """Liveness: the process answers. No dependency probes."""
    return {"status": "ok", "version": APP_VERSION}


@router.get("/health", summary="Health summary — gated by CRITICAL deps only")
async def health_check() -> JSONResponse:
    """Readiness-style health: 200 iff every CRITICAL dependency is up.

    Optional dependencies are included in the payload as informational
    flags so dashboards can see them without paging on them.
    """
    redis_ok, flare_ok, ollama_ok = await asyncio.gather(
        _check_redis(), _check_flaresolverr(), _check_ollama(), return_exceptions=False
    )
    deps = {
        "redis": redis_ok,  # CRITICAL
        "flaresolverr": flare_ok,  # optional — informational
        "ollama": ollama_ok,  # optional — informational
    }
    healthy = redis_ok
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "version": APP_VERSION,
            "dependencies": deps,
        },
    )


@router.get("/live", summary="Kubernetes liveness probe")
async def live() -> dict[str, str]:
    """Simple liveness — always returns 200 if the process is running."""
    return {"status": "alive"}


@router.get("/ready", summary="Kubernetes readiness probe", response_model=None)
async def ready() -> JSONResponse | dict[str, str]:
    """Readiness — CRITICAL dependencies only (redis).

    NOTE: this deliberately does NOT probe Ollama or FlareSolverr. Both are
    optional enhancement tiers; gating readiness on them caused the
    2026-08-21 four-day false-unhealthy incident.
    """
    if await _check_redis():
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not_ready"})


@router.get("/version", summary="Service version")
async def version() -> dict[str, str]:
    """Return service version information."""
    return {
        "version": settings.app_version,
        "service": settings.app_name,
        "status": "operational",
    }
