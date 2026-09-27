"""Pry — Diagnostics router (fallback telemetry observability).

Exposes WHY intelligent-fallback tiers won or lost so operators can
debug the fallback chain without digging through logs.

Endpoints:
  GET /v1/diagnostics — snapshot of fallback telemetry
    (ring stats, aggregate + per-domain stats, recent records)
  GET /v1/diagnostics/method-plan?domain=example.com — the learned method
    memory for one domain: ranked tier order with per-tier success rate,
    sample count, latency, cost, last_block_kind, plus the plain-language
    reason for the top pick. Internal/free (see the internal-token path) and
    explicitly NOT an x402-paid endpoint.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from pry.engine import fallback_telemetry
from pry.engine.method_memory_view import domain_method_plan


def _require_auth(request: Request) -> None:
    """Fail-closed guard matching the middleware auth pattern."""
    from pry.api.api import request_authorized

    if not request_authorized(request.scope):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: valid API key required (or loopback client when no key is configured)",
        )


router = APIRouter(tags=["Diagnostics"])


@router.get(
    "/v1/diagnostics",
    summary="Fallback telemetry diagnostics",
    dependencies=[Depends(_require_auth)],
)
async def diagnostics() -> dict[str, Any]:
    """Snapshot of fallback-telemetry state (why tiers won/lost)."""
    return {"success": True, "data": {"fallback": fallback_telemetry.snapshot()}}


@router.get(
    "/v1/diagnostics/method-plan",
    summary="Learned method memory for one domain (why a fetch is ordered this way)",
    dependencies=[Depends(_require_auth)],
)
async def method_plan(domain: str = Query(..., min_length=1, max_length=253)) -> dict[str, Any]:
    """Ranked tier order + per-tier evidence for ``domain``.

    Answers "how should I fetch this domain?" from the same learned memory the
    scraper ranks with, so a caller never gets a plan the engine would not
    follow. Free for first-party/internal callers via the standard internal
    credential path (``_require_auth``) — no x402 payment, no per-call price.
    A domain with no history returns an empty ``tiers`` list and a cold-start
    reason rather than an invented ordering.
    """
    return {"success": True, "data": domain_method_plan(domain)}
