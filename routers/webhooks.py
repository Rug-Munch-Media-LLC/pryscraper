"""Pry — Webhooks router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])

@router.post(
    "/v1/webhooks/test",
    tags=["Webhooks"],
    summary="Test webhook delivery",
)
async def test_webhook(
    url: str = Body(...),
    payload: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Test webhook delivery to a URL with HMAC signing."""
    from webhook_delivery import WebhookDelivery

    w = WebhookDelivery()
    return await w.deliver(url, payload or {"test": True, "timestamp": "now"}, "test.event")


@router.get(
    "/v1/webhooks/dead-letter",
    tags=["Webhooks"],
    summary="Get failed webhook deliveries",
)
async def get_dead_letter() -> dict[str, Any]:
    """Get the dead letter queue of failed webhook deliveries."""
    from webhook_delivery import WebhookDelivery

    w = WebhookDelivery()
    return {"success": True, "data": w.retry_dead_letter()}
