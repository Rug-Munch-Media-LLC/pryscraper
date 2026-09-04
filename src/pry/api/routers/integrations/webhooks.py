"""Pry — Webhooks router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.parse
from typing import Any

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])


def _validate_webhook_url(url: str) -> str | None:
    """Validate a webhook URL to prevent SSRF.

    Returns ``None`` if the URL is safe, otherwise a human-readable reason
    describing why validation failed.
    """
    parsed = urllib.parse.urlparse(url)

    host = parsed.hostname
    if not host:
        return "missing host"

    # Reject non-https schemes; allow http only for localhost.
    if parsed.scheme != "https":
        if parsed.scheme == "http" and host in ("localhost", "127.0.0.1", "::1"):
            pass
        else:
            return f"unsupported scheme: {parsed.scheme!r}"

    # Resolve the host to its IP address(es).
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return f"could not resolve host: {host}"

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return f"resolved to private/loopback/link-local address: {ip}"

    return None


@router.post(
    "/v1/webhooks/test",
    tags=["Webhooks"],
    summary="Test webhook delivery",
)
async def webhook_test_route(
    url: str = Body(...),
    payload: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    """Test webhook delivery to a URL with HMAC signing."""
    from pry.api.webhook_delivery import WebhookDelivery

    reason = _validate_webhook_url(url)
    if reason is not None:
        return {"success": False, "error": f"URL validation failed: {reason}"}

    w = WebhookDelivery()
    return await w.deliver(url, payload or {"test": True, "timestamp": "now"}, "test.event")


@router.get(
    "/v1/webhooks/dead-letter",
    tags=["Webhooks"],
    summary="Get failed webhook deliveries",
)
async def get_dead_letter() -> dict[str, Any]:
    """Get the dead letter queue of failed webhook deliveries."""
    from pry.api.webhook_delivery import WebhookDelivery

    w = WebhookDelivery()
    return {"success": True, "data": w.retry_dead_letter()}
