"""Pry — Diagnostics router (fallback telemetry observability).

Exposes WHY intelligent-fallback tiers won or lost so operators can
debug the fallback chain without digging through logs.

Endpoint:
  GET /v1/diagnostics — snapshot of fallback telemetry
    (ring stats, aggregate + per-domain stats, recent records)

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

import fallback_telemetry

router = APIRouter(tags=["Diagnostics"])


@router.get("/v1/diagnostics", summary="Fallback telemetry diagnostics")
async def diagnostics() -> dict[str, Any]:
    """Snapshot of fallback-telemetry state (why tiers won/lost)."""
    return {"success": True, "data": {"fallback": fallback_telemetry.snapshot()}}
