"""Pry — Config router (runtime configuration management).

Provides endpoints to read and update the unified Pry settings object.
Runtime changes are persisted to the configured JSON file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from pry.core.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Config"])


def require_sensitive_config_auth(request: Request) -> None:
    """Fail-closed guard for egress configuration endpoints.

    Mirrors the app middleware (api.py request_authorized): with PRY_API_KEY
    set, a valid Bearer credential is required from any source; without a key,
    only loopback clients may change proxy/tor egress configuration.
    """
    from pry.api.api import request_authorized

    if not request_authorized(request.scope):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: valid API key required (or loopback client when no key is configured)",
        )


@router.get("/v1/config", tags=["Config"], summary="Get current Pry configuration")
async def get_config() -> dict[str, Any]:
    """Get current Pry configuration."""
    return {"success": True, "data": settings.to_api_dict()}


@router.post(
    "/v1/config",
    tags=["Config"],
    summary="Update Pry configuration at runtime",
    dependencies=[Depends(require_sensitive_config_auth)],
)
async def update_config(updates: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Update Pry configuration at runtime.

    Proxy/tor settings can hijack egress, so this endpoint requires the same
    fail-closed auth as the middleware: key required when PRY_API_KEY is set,
    loopback-only when it is not.
    """
    result = settings.update(updates)
    return {"success": True, "data": result}


@router.post(
    "/v1/config/profile/tor",
    tags=["Config"],
    summary="Enable Tor routing for all requests",
    dependencies=[Depends(require_sensitive_config_auth)],
)
async def enable_tor() -> dict[str, Any]:
    """Enable Tor routing for all requests."""
    result = settings.enable_tor()
    resp_data = {
        "success": True,
        "data": result,
        "note": "Run 'docker compose --profile tor up -d' to start Tor container",
    }
    return resp_data
