"""Pry — Circuit Breaker router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Circuit Breaker"])


@router.post("/v1/breaker/status", tags=["Circuit Breaker"], summary="Get circuit breaker status")
async def breaker_status() -> dict[str, Any]:
    return {
        "success": True,
        "data": {k: {"fails": v, "backoff": min(2**v, 60)} for k, v in _failures.items()},
    }


@router.post(
    "/v1/breaker/reset", tags=["Circuit Breaker"], summary="Reset circuit breaker for a domain"
)
async def breaker_reset(domain: str = Body("")) -> dict[str, Any]:
    if domain:
        _failures.pop(domain, None)
    else:
        _failures.clear()
    return {"success": True, "data": {"cleared": domain or "all"}}


_failures: dict[str, int] = {}
