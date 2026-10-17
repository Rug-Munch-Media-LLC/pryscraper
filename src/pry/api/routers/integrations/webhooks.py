"""Pry — Webhooks router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])


async def _require_auth(request: Request) -> None:
    """Inline auth check — import from core.middleware to avoid cross-domain boundary."""
    from pry.core.middleware import request_authorized

    if not request_authorized(request.scope):
        raise HTTPException(status_code=401, detail="unauthorized")


# Cap concurrent webhook test deliveries: each can hold a worker for up to
# the delivery timeout (~15s), so unbounded concurrency risks worker exhaustion.
_webhook_test_sem = asyncio.Semaphore(3)


def _validate_webhook_url(url: str) -> str | None:
    """Validate a webhook URL to prevent SSRF.

    Delegates to the DNS-pinning validator in :mod:`pry.api.webhook_delivery`.
    A second, weaker copy of this check previously lived here: it resolved the
    host and inspected the addresses but then threw them away, so the delivery
    client re-resolved the name at connect time and a rebinding resolver could
    hand httpx a private address the check never saw. One validator, one
    answer, and the pinned URL is what actually gets fetched.

    Returns ``None`` if the URL is safe, otherwise a human-readable reason
    describing why validation failed.
    """
    from pry.api.webhook_delivery import _validate_url

    _, reason = _validate_url(url)
    return reason


@router.post(
    "/v1/webhooks/test",
    tags=["Webhooks"],
    summary="Test webhook delivery",
)
async def webhook_test_route(
    url: str = Body(...),
    payload: dict[str, Any] | None = Body(None),
    _: None = Depends(_require_auth),
) -> dict[str, Any]:
    """Test webhook delivery to a URL with HMAC signing."""
    from pry.api.webhook_delivery import WebhookDelivery

    reason = _validate_webhook_url(url)
    if reason is not None:
        return {"success": False, "error": f"URL validation failed: {reason}"}

    w = WebhookDelivery()
    async with _webhook_test_sem:
        return await w.deliver(url, payload or {"test": True, "timestamp": "now"}, "test.event")


@router.get(
    "/v1/webhooks/dead-letter",
    tags=["Webhooks"],
    summary="Get failed webhook deliveries",
)
async def get_dead_letter(_: None = Depends(_require_auth)) -> dict[str, Any]:
    """Get the dead letter queue of failed webhook deliveries."""
    from pry.api.webhook_delivery import WebhookDelivery

    w = WebhookDelivery()
    return {"success": True, "data": w.retry_dead_letter()}
