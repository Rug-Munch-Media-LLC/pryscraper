"""x402 ASGI enforcement middleware (audit E41 split).

``X402Middleware`` / ``X402_RATE_LIMIT_PER_MIN`` stay here (tests monkeypatch
this module); stages live in ``enforcement_stages`` / ``enforcement_payment``."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import json
import logging
import os
from typing import Any

from pry.core.audit import audit_event  # noqa: F401  (patch/monkeypatch surface)
from pry.core.ratelimit import RateLimiter
from pry.core.settings import settings
from pry.payments.x402 import X402Handler, validate_client_amount  # noqa: F401
from pry.payments.x402_middleware import config as _pricing_config  # noqa: F401
from pry.payments.x402_middleware.classification import (
    DEFAULT_FREE_PATHS,
    DEFAULT_FREE_PREFIXES,
    _admin_prefix,
    _caller_key_from_scope,
    resolve_operation,
)
from pry.payments.x402_middleware.config import X402_GATE_MISCONFIGURED  # noqa: F401
from pry.payments.x402_middleware.credential import (  # noqa: F401  (patch surface)
    valid_api_key_credential,
)
from pry.payments.x402_middleware.enforcement_payment import _handle_presented_payment
from pry.payments.x402_middleware.enforcement_response import (
    X402_PAYMENT_HEADER_MAX_BYTES,
    _compact_payment_required_header,
)
from pry.payments.x402_middleware.enforcement_stages import (
    _bypass_gate,
    _check_rate_limit,
    _is_misconfigured,
    _send_misconfigured,
    _serve_preverified_batch,
    _serve_preverified_payment,
)
from pry.payments.x402_middleware.enforcement_verify import (
    _decode_presented_payment_required,  # noqa: F401
)
from pry.payments.x402_middleware.internal import (  # noqa: F401  (patch surface)
    internal_request,
    mark_internal_verified,
)
from pry.payments.x402_middleware.owner import (  # noqa: F401  (patch surface)
    mark_owner_verified,
    owner_request,
)

logger = logging.getLogger(__name__)

# Per-IP rate limit for the x402 gate itself (402 challenges + settle
# attempts). X402Middleware sits OUTERMOST (api.py), so it runs BEFORE
# PryHttpMiddleware's global limiter — without its own limiter a keyless
# agent could hammer 402 challenges / facilitator verify+settle calls
# unthrottled. Redis-backed via settings.redis_url (degrades to per-process
# token bucket when Redis is down — see pry/core/ratelimit.py).
X402_RATE_LIMIT_PER_MIN = int(os.getenv("X402_RATE_LIMIT_PER_MIN", "120"))


class X402Middleware:
    """ASGI middleware that gates paid endpoints behind x402 payments.

    Headers (x402 v1 spec):
    - Request: ``PAYMENT-SIGNATURE: <Base64(JSON of {payment_id, tx_hash, ...})>``
    - 402 response: ``PAYMENT-REQUIRED: <Base64(JSON PaymentRequired)>``
    - 2xx response: ``PAYMENT-RESPONSE: <Base64(JSON settlement receipt)>``
    """

    def __init__(
        self,
        app: Any,
        free_paths: list[str] | None = None,
        free_prefixes: list[str] | None = None,
        wallet: str = "pry-default",
        network: str = "base",
        facilitator_url: str = "https://x402.org/facilitator",
    ) -> None:
        self.app = app
        self.free_paths: frozenset[str] = frozenset(
            free_paths if free_paths is not None else DEFAULT_FREE_PATHS
        )
        self.free_prefixes: tuple[str, ...] = tuple(
            free_prefixes if free_prefixes is not None else DEFAULT_FREE_PREFIXES
        )
        self.wallet = wallet
        self.network = network
        self.facilitator_url = facilitator_url
        self.handler = X402Handler(wallet=wallet, facilitator_url=facilitator_url)
        # NOTE: no per-instance payments cache here — payment state lives in
        # X402Handler (persisted to payments.jsonl). A previous in-memory
        # ``self.payments`` dict was write-only dead code (memory-leak audit
        # HIGH finding) and has been removed.
        self.limiter = RateLimiter(
            default_rpm=X402_RATE_LIMIT_PER_MIN,
            burst=X402_RATE_LIMIT_PER_MIN,
            redis_url=settings.redis_url,
        )

    def _is_free(self, path: str) -> bool:
        """Exact/prefix/admin free-path check (wildcard-aware)."""
        if path in self.free_paths:
            return True
        if any(path.startswith(p) for p in self.free_prefixes):
            return True
        return path.startswith(_admin_prefix())

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        # Non-HTTP / preflight / owner / internal / free / Bearer bypasses.
        if await _bypass_gate(self, scope, receive, send):
            return

        path = scope.get("path", "")
        # Resolve the operation once, up front, so server-side pricing can be
        # enforced against any client-supplied amount.
        operation = resolve_operation(path)
        if not operation:
            # No paid prefix matched. The startup audit guarantees every route
            # is classified; reaching here means the request path escaped both
            # the free lists and PAID_ENDPOINTS (e.g. a dynamic path not backed
            # by a registered route). Serve it — 404s from the router are the
            # correct response for unknown paths, not a payment challenge.
            await self.app(scope, receive, send)
            return
        if _is_misconfigured(operation):
            # FAIL CLOSED: a paid prefix without pricing is a deployment bug.
            # The previous behavior silently served the endpoint for free.
            await _send_misconfigured(send, operation, path)
            return

        caller_key = _caller_key_from_scope(scope)

        # Per-IP rate limit (audit hardening): the gate is outermost, so this
        # is the ONLY limiter a keyless 402-challenge / settle request hits.
        # IP-based (socket peer — X-Forwarded-For is spoofable); the inner
        # PryHttpMiddleware adds API-key-based limiting for authenticated
        # traffic on top of this.
        if not await _check_rate_limit(self, caller_key, path, send):
            return

        headers = dict(scope.get("headers", []))
        payment_sig = headers.get(b"payment-signature", b"").decode()
        payment_id_header = headers.get(b"x-payment-id", b"").decode()
        batch_id_header = headers.get(b"x-batch-payment-id", b"").decode()

        # Check pre-verified individual payment (expiry + caller-bound);
        # refresh first so /v1/x402/pay payments are visible here.
        if await _serve_preverified_payment(
            self, scope, receive, send, payment_id_header, caller_key, operation
        ):
            return

        # Check pre-verified batch payment.
        if await _serve_preverified_batch(
            self, scope, receive, send, batch_id_header, caller_key, operation
        ):
            return

        if payment_sig and await _handle_presented_payment(
            self, payment_sig, operation, caller_key, path, scope, receive, send
        ):
            return

        await self._send_payment_required(operation, path, send)

    async def _send_payment_required(self, operation: str, path: str, send: Any) -> None:
        """Send a spec-compliant 402 Payment Required response.

        Built in multi-asset mode so agents see the full acceptance surface;
        the PAYMENT-REQUIRED header is compacted under
        X402_PAYMENT_HEADER_MAX_BYTES (Cloudflare 502s larger single headers —
        2026-08-25 incident).
        """
        body, x402_headers = self.handler.create_payment_required(
            operation, resource=path, multi_asset=True
        )
        x402_headers["PAYMENT-REQUIRED"] = _compact_payment_required_header(
            body, X402_PAYMENT_HEADER_MAX_BYTES
        )
        body_bytes = json.dumps(body).encode()

        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body_bytes)).encode()),
        ]
        for k, v in x402_headers.items():
            response_headers.append((k.lower().encode(), v.encode()))

        await send(
            {
                "type": "http.response.start",
                "status": 402,
                "headers": response_headers,
            }
        )
        await send({"type": "http.response.body", "body": body_bytes})
