"""Pry — Marketplace router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Marketplace"])

@router.post(
    "/v1/actors/create",
    tags=["Marketplace"],
    summary="Create a new actor",
)
async def create_actor(
    name: str = Body(...),
    description: str = Body(...),
    template_id: str = Body(""),
    code: str = Body(""),
    price_per_run: float = Body(0.0),
    visibility: str = Body("private"),
    schedule_cron: str = Body(""),
    tags: list[str] | None = Body(None),
) -> dict[str, Any]:
    """Create a new actor in the marketplace."""
    from actor_marketplace import ActorMarketplace, ActorVisibility

    m = ActorMarketplace()
    actor = m.create(
        name,
        description,
        template_id,
        code,
        price_per_run,
        ActorVisibility(visibility),
        schedule_cron,
        tags or [],
    )
    return {"success": True, "data": actor.to_dict()}


@router.get(
    "/v1/actors",
    tags=["Marketplace"],
    summary="List actors in the marketplace",
)
async def list_actors(visibility: str = "", tag: str = "") -> dict[str, Any]:
    """List actors. Filter by visibility (public/private) and tag."""
    from actor_marketplace import ActorMarketplace

    m = ActorMarketplace()
    return {"success": True, "data": m.list(visibility, tag)}


@router.post(
    "/v1/actors/{actor_id}/run",
    tags=["Marketplace"],
    summary="Run an actor",
)
async def run_actor(actor_id: str, inputs: dict[str, Any] | None = Body(None)) -> dict[str, Any]:
    """Run an actor with the provided inputs."""
    from actor_marketplace import ActorMarketplace

    m = ActorMarketplace()
    return await m.run(actor_id, inputs or {})
