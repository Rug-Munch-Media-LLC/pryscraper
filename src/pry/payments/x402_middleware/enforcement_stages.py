"""Early-stage helpers extracted from ``X402Middleware.__call__``.

Misconfiguration fail-closed, the per-IP limiter, and the pre-verified
single/batch payment paths. Behavior-preserving: each returns a decision so
``__call__`` stays a thin dispatcher.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import logging
from typing import Any

from pry.payments.x402 import is_batch_paid
from pry.payments.x402_middleware import config as _pricing_config
from pry.payments.x402_middleware.config import X402_GATE_MISCONFIGURED
from pry.payments.x402_middleware.enforcement_response import _send_json_response

logger = logging.getLogger(__name__)


async def _bypass_gate(mw: Any, scope: dict[str, Any], receive: Any, send: Any) -> bool:
    """Serve non-gated requests directly; True when the request was passed.

    Covers non-HTTP scopes, CORS preflight, owner access, first-party internal
    calls, free paths and valid Bearer credentials — all unchanged from the
    original inline sequence.
    """
    from pry.payments.x402_middleware.credential import valid_api_key_credential
    from pry.payments.x402_middleware.internal import (
        internal_request,
        mark_internal_verified,
    )
    from pry.payments.x402_middleware.owner import mark_owner_verified, owner_request

    if scope["type"] != "http" or scope.get("method") == "OPTIONS":
        await mw.app(scope, receive, send)
        return True
    path = scope.get("path", "")
    headers = dict(scope.get("headers", []))
    if owner_request(headers):
        mark_owner_verified(scope)
        await mw.app(scope, receive, send)
        return True
    if internal_request(scope, headers):
        mark_internal_verified(scope)
        await mw.app(scope, receive, send)
        return True
    if mw._is_free(path) or valid_api_key_credential(headers):
        await mw.app(scope, receive, send)
        return True
    return False


def _is_misconfigured(operation: str) -> bool:
    """True when a resolved paid operation has no configured price."""
    return operation not in _pricing_config.X402_PRICING


async def _send_misconfigured(send: Any, operation: str, path: str) -> None:
    """Send the 500 fail-closed response for a priced-but-unconfigured gate."""
    logger.critical(
        "x402_gate_misconfigured",
        extra={"operation": operation, "path": path},
    )
    if X402_GATE_MISCONFIGURED is not None:
        X402_GATE_MISCONFIGURED.inc()
    await _send_json_response(
        send,
        500,
        {
            "error": "payment_gate_misconfigured",
            "detail": "endpoint is gated but its price is not configured",
        },
    )


async def _check_rate_limit(mw: Any, caller_key: str, path: str, send: Any) -> bool:
    """Return True when the caller passed the per-IP limiter; send 429 if not."""
    allowed, rate_stats = mw.limiter.check(caller_key or "unknown")
    if allowed:
        return True
    retry_after = rate_stats.get("retry_after", 1)
    logger.warning(
        "x402_rate_limited",
        extra={"path": path, "ip": caller_key, "retry_after": retry_after},
    )
    await _send_json_response(
        send,
        429,
        {
            "error": "rate_limit_exceeded",
            "detail": "too many payment requests; retry later",
            "retry_after": retry_after,
        },
        [(b"retry-after", str(int(float(retry_after))).encode())],
    )
    return False


async def _serve_preverified_payment(
    mw: Any,
    scope: dict[str, Any],
    receive: Any,
    send: Any,
    payment_id_header: str,
    caller_key: str,
    operation: str,
) -> bool:
    """Serve a pre-verified single payment; True when the request was passed.

    Refreshes handler state first so payments issued by other handlers are
    visible, then marks ``x402_verified`` when the payment is valid AND a
    successful settlement receipt is bound to the same payment_id.

    ``is_paid`` alone only proves verification — a verified-but-unsettled
    payment must never buy service (settle fail-closed, P0).
    """
    if not payment_id_header:
        return False
    mw.handler.refresh()
    if not mw.handler.is_paid(payment_id_header, caller_key=caller_key, operation=operation):
        return False
    from pry.payments.x402.settlement_gate import is_settled

    if not is_settled(mw.handler, payment_id_header):
        logger.warning(
            "x402_payment_not_settled",
            extra={"payment_id": payment_id_header, "operation": operation},
        )
        return False
    scope["x402_verified"] = {
        "payment_id": payment_id_header,
        "caller": caller_key,
        "operation": operation,
    }
    await mw.app(scope, receive, send)
    return True


async def _serve_preverified_batch(
    mw: Any,
    scope: dict[str, Any],
    receive: Any,
    send: Any,
    batch_id_header: str,
    caller_key: str,
    operation: str,
) -> bool:
    """Serve a pre-verified batch payment; True when the request was passed."""
    if not batch_id_header:
        return False
    if not is_batch_paid(batch_id_header, caller_key=caller_key, operation=operation):
        return False
    scope["x402_verified"] = {
        "batch_id": batch_id_header,
        "caller": caller_key,
        "operation": operation,
    }
    await mw.app(scope, receive, send)
    return True
