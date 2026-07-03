"""Pry — Config router (runtime configuration management).

Provides endpoints to read and update the unified Pry settings object.
Runtime changes are persisted to the configured JSON file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Config"])


@router.get("/v1/config", tags=["Config"], summary="Get current Pry configuration")
async def get_config() -> dict[str, Any]:
    """Get current Pry configuration."""
    return {"success": True, "data": settings.to_api_dict()}


@router.post("/v1/config", tags=["Config"], summary="Update Pry configuration at runtime")
async def update_config(updates: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Update Pry configuration at runtime."""
    result = settings.update(updates)
    return {"success": True, "data": result}


@router.post("/v1/config/profile/tor", tags=["Config"], summary="Enable Tor routing for all requests")
async def enable_tor() -> dict[str, Any]:
    """Enable Tor routing for all requests."""
    result = settings.enable_tor()
    resp_data = {
        "success": True,
        "data": result,
        "note": "Run 'docker compose --profile tor up -d' to start Tor container",
    }
    return resp_data
