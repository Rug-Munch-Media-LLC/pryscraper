"""Pry — Health router (liveness, readiness, dependency probes).

Split from api.py. Replaces the inline /health, /live, /ready endpoints.

Endpoints (3):
  GET /health    — Full health check with dependency status
  GET /live      — Kubernetes liveness probe
  GET /ready     — Kubernetes readiness probe

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import asyncio

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from client import get_client
from settings import settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Full health check with dependency status")
async def health_check() -> JSONResponse:
    """Comprehensive health check — probes Ollama, FlareSolverr, Redis."""
    deps = {"ollama": False, "flaresolverr": False, "redis": False}

    async def check_ollama() -> bool:
        try:
            c = await get_client()
            r = await c.get(f"{settings.ollama_url}/api/tags", timeout=3)
            return r.is_success
        except Exception:  # noqa: BLE001
            return False

    async def check_flare() -> bool:
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

    async def check_redis() -> bool:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(settings.redis_url)
            await r.ping()
            await r.close()  # type: ignore[attr-defined]  # redis.asyncio.Redis has close() in older stubs
            return True
        except redis.RedisError:
            return False

    results = await asyncio.gather(
        check_ollama(), check_flare(), check_redis(), return_exceptions=False
    )
    deps["ollama"] = results[0]
    deps["flaresolverr"] = results[1]
    deps["redis"] = results[2]
    flaresolverr_ok = deps["flaresolverr"]
    status_code = 200 if flaresolverr_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if flaresolverr_ok else "degraded",
            "version": "3.0.0",
            "dependencies": deps,
        },
    )


@router.get("/live", summary="Kubernetes liveness probe")
async def live() -> dict[str, str]:
    """Simple liveness — always returns 200 if the process is running."""
    return {"status": "alive"}


@router.get("/ready", summary="Kubernetes readiness probe", response_model=None)
async def ready() -> JSONResponse | dict[str, str]:
    """Readiness — checks critical dependencies."""
    try:
        c = await get_client()
        r = await c.get(f"{settings.ollama_url}/api/tags", timeout=3)
        if r.is_success:
            return {"status": "ready"}
    except Exception:  # noqa: BLE001, S110 - readiness probe: any failure => not ready
        pass
    return JSONResponse(status_code=503, content={"status": "not_ready"})


@router.get("/version", summary="Service version")
async def version() -> dict[str, str]:
    """Return service version information."""
    return {
        "version": settings.app_version,
        "service": settings.app_name,
        "status": "operational",
    }
