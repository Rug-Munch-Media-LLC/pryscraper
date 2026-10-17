"""Owner (self-hosted) request detection for the x402 gate.

x402 is the revenue path for external callers. Our own CLI, MCP server,
internal services and self-hosted tooling authenticate with the owner API key
(``PRY_API_KEY``) and must never be charged or blocked by the payment gate.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import hmac
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

OWNER_SCOPE_KEY = "x402_verified"


def owner_key() -> str:
    """Return the configured owner API key (env first, then app settings)."""
    key = (os.environ.get("PRY_API_KEY") or "").strip()
    if key:
        return key
    try:
        from pry.core.settings import settings  # app-level config
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "owner_key"},
        )
        return ""
    return str(getattr(settings, "api_key", "") or "").strip()


def owner_request(headers: dict[bytes, bytes]) -> bool:
    """True when the request carries the owner credential (Bearer or X-API-Key)."""
    key = owner_key()
    if not key:
        return False
    bearer = headers.get(b"authorization", b"").decode()
    token = (
        bearer[7:]
        if bearer.lower().startswith("bearer ")
        else headers.get(b"x-api-key", b"").decode()
    )
    return bool(token) and hmac.compare_digest(token.strip(), key)


def mark_owner_verified(scope: dict[str, Any]) -> None:
    """Mark the ASGI scope so the inner API-key auth layer accepts the call.

    The auth layer reads ``payment_id``/``batch_id`` from this marker (it is a
    payment-shaped dict, not a bool — a bool crashes middleware_auth with
    AttributeError), so owner calls present the same shape as verified payments.
    """
    scope[OWNER_SCOPE_KEY] = {"payment_id": "owner", "batch_id": "", "owner": True}
