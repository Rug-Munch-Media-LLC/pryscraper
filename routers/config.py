"""Pry — Config router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from mconfig import PryConfig

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Config"])

@router.get("/v1/config", tags=["Config"], summary="Get current Pry configuration")
async def get_config() -> dict[str, Any]:
    """Get current Pry configuration."""
    return {"success": True, "data": config.to_dict()}


@router.post("/v1/config", tags=["Config"], summary="Update Pry configuration at runtime")
async def update_config(updates: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Update Pry configuration at runtime."""
    result = config.update(updates)
    return {"success": True, "data": result}


@router.post("/v1/config/profile/tor", tags=["Config"], summary="Enable Tor routing for all requests")
async def enable_tor() -> dict[str, Any]:
    """Enable Tor routing for all requests."""
    result = config.update(
        {"tor": {"enabled": True}, "proxy": {"enabled": True, "url": "socks5://tor:9050"}}
    )
    resp_data = {
        "success": True,
        "data": result,
        "note": "Run 'docker compose --profile tor up -d' to start Tor container",
    }
    return resp_data


config = PryConfig()
