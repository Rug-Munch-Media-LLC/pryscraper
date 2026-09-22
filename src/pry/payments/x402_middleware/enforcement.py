"""x402 ASGI enforcement middleware (audit E41 split).
``X402Middleware``/``X402_RATE_LIMIT_PER_MIN`` stay here (tests monkeypatch
this module); verify/response helpers are re-exported for compatibility."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import base64
import json
import logging
import os
from typing import Any

from pry.core.audit import audit_event
from pry.core.ratelimit import RateLimiter
from pry.core.settings import settings
from pry.payments.x402 import X402Handler, validate_client_amount
from pry.payments.x402_middleware import config as _pricing_config
from pry.payments.x402_middleware.classification import (
    DEFAULT_FREE_PATHS,
    DEFAULT_FREE_PREFIXES,
    _admin_prefix,
    _caller_key_from_scope,
    resolve_operation,
)
from pry.payments.x402_middleware.config import X402_GATE_MISCONFIGURED
from pry.payments.x402_middleware.enforcement_response import (
    X402_PAYMENT_HEADER_MAX_BYTES,
    _compact_payment_required_header,
)
from pry.payments.x402_middleware.enforcement_verify import (
    _attested_required_atomic,
    _decode_presented_payment_required,  # noqa: F401
    _verify_presented_attestation,
)
from pry.payments.x402_middleware.owner import mark_owner_verified, owner_request

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
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # CORS preflight: OPTIONS requests carry no credentials or body and must
        # reach CORSMiddleware so browsers get the Access-Control-Allow-* headers.
        # Never gate preflight behind payment.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        # Self-hosted owner access: the owner key skips payment entirely and is
        # accepted by the inner auth layer (same credential). External callers
        # still receive the 402 challenge — revenue path unchanged.
        headers = dict(scope.get("headers", []))
        if owner_request(headers):
            mark_owner_verified(scope)
            await self.app(scope, receive, send)
            return
        if self._is_free(path):
            await self.app(scope, receive, send)
            return

        # Bearer-credentialed requests (hosted API keys, server-to-server
        # callers such as the MCP dispatch) bypass the payment gate: the
        # inner PryHttpMiddleware authenticates the credential (401 on
        # invalid) and the BillingEnforcer meters/bills the key against its
        # tier quota. The gate's job is to monetize KEYLESS agent traffic —
        # credentialed traffic has its own billing path. Without this bypass
        # every hosted API-key customer gets 402-challenged on paid endpoints.
        _auth_header = dict(scope.get("headers", [])).get(b"authorization", b"")
        if _auth_header.startswith(b"Bearer ") and len(_auth_header) > 7:
            await self.app(scope, receive, send)
            return

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
        if operation not in _pricing_config.X402_PRICING:
            # FAIL CLOSED: a paid prefix without pricing is a deployment bug.
            # The previous behavior silently served the endpoint for free.
            logger.critical(
                "x402_gate_misconfigured",
                extra={"operation": operation, "path": path},
            )
            if X402_GATE_MISCONFIGURED is not None:
                X402_GATE_MISCONFIGURED.inc()
            body = json.dumps(
                {
                    "error": "payment_gate_misconfigured",
                    "detail": "endpoint is gated but its price is not configured",
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        caller_key = _caller_key_from_scope(scope)

        # Per-IP rate limit (audit hardening): the gate is outermost, so this
        # is the ONLY limiter a keyless 402-challenge / settle request hits.
        # IP-based (socket peer — X-Forwarded-For is spoofable); the inner
        # PryHttpMiddleware adds API-key-based limiting for authenticated
        # traffic on top of this.
        allowed, rate_stats = self.limiter.check(caller_key or "unknown")
        if not allowed:
            logger.warning(
                "x402_rate_limited",
                extra={
                    "path": path,
                    "ip": caller_key,
                    "retry_after": rate_stats.get("retry_after", 1),
                },
            )
            body = json.dumps(
                {
                    "error": "rate_limit_exceeded",
                    "detail": "too many payment requests; retry later",
                    "retry_after": rate_stats.get("retry_after", 1),
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (
                            b"retry-after",
                            str(int(float(rate_stats.get("retry_after", 1)))).encode(),
                        ),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        headers = dict(scope.get("headers", []))
        payment_sig = headers.get(b"payment-signature", b"").decode()
        payment_id_header = headers.get(b"x-payment-id", b"").decode()
        batch_id_header = headers.get(b"x-batch-payment-id", b"").decode()

        # Check pre-verified individual payment (expiry + caller-bound).
        # Refresh first so payments issued by other handlers (e.g. the
        # /v1/x402/pay route) are visible to this middleware instance.
        if payment_id_header:
            self.handler.refresh()
            if self.handler.is_paid(payment_id_header, caller_key=caller_key, operation=operation):
                # Payment IS the credential: mark verified so the inner
                # auth layer accepts the request without an API key.
                scope["x402_verified"] = {
                    "payment_id": payment_id_header,
                    "caller": caller_key,
                    "operation": operation,
                }
                await self.app(scope, receive, send)
                return

        # Check pre-verified batch payment
        if batch_id_header:
            from pry.payments.x402 import is_batch_paid

            if is_batch_paid(batch_id_header, caller_key=caller_key, operation=operation):
                scope["x402_verified"] = {
                    "batch_id": batch_id_header,
                    "caller": caller_key,
                    "operation": operation,
                }
                await self.app(scope, receive, send)
                return

        if payment_sig:
            try:
                payload = json.loads(base64.b64decode(payment_sig).decode())
                payment_id = payload.get("payment_id", "")
                tx_hash = payload.get("tx_hash", "") or payload.get("payload", "")
                network = payload.get("network", self.network)
                asset = payload.get("asset", "")
                amount_usd = float(payload.get("amount_usd", 0.0))
                if payment_id and tx_hash:
                    # Audit #1 gate: if the client echoes the payment-required
                    # body it received, verify the server attestation so a
                    # MITM-rewritten payTo/amount/network challenge is refused
                    # before any verify/settle runs. Unattested bodies (no key
                    # configured at issue time) still pass (legacy); an
                    # INVALID attestation fails closed with a fresh 402.
                    attest_ok, attest_reason, attest_body = _verify_presented_attestation(payload)
                    if not attest_ok:
                        audit_event(
                            "x402_attestation_rejected",
                            actor=caller_key,
                            path=path,
                            operation=operation,
                            payment_id=payment_id,
                            reason=attest_reason,
                        )
                        logger.warning(
                            "x402_attestation_failed",
                            extra={
                                "operation": operation,
                                "path": path,
                                "payment_id": payment_id,
                                "reason": attest_reason,
                            },
                        )
                        await self._send_payment_required(operation, path, send)
                        return
                    # Price binding (audit #7): when the echoed 402 body is
                    # ATTESTED and verified, its SIGNED maxAmountRequired is
                    # the authoritative required amount for the volatile-asset
                    # comparison downstream (self-facilitator verify). The
                    # cross-operation price check below is UNCHANGED.
                    attested_atomic = _attested_required_atomic(attest_body, network, asset)
                    # Server-side pricing is authoritative: never trust the
                    # client-supplied amount. Reject underpayment BEFORE any
                    # facilitator call. ``network`` lets the canonical
                    # SUPPORTED_ASSETS table quote non-1:1 assets correctly.
                    ok, price_reason = validate_client_amount(
                        operation, amount_usd, asset, network=network
                    )
                    if not ok:
                        audit_event(
                            "x402_underpayment_rejected",
                            actor=caller_key,
                            path=path,
                            operation=operation,
                            reason=price_reason,
                        )
                        logger.warning(
                            "x402_underpayment_rejected",
                            extra={"operation": operation, "path": path, "reason": price_reason},
                        )
                        await self._send_payment_required(operation, path, send)
                        return
                    verify_result = await self.handler.verify_payment(
                        payment_id,
                        tx_hash,
                        network=network,
                        asset=asset,
                        amount_usd=amount_usd,
                        operation=operation,
                        caller_key=caller_key,
                        attested_required_atomic=attested_atomic,
                    )
                    if verify_result.get("verified"):
                        settlement = await self.handler.settle_payment(
                            payment_id,
                            tx_hash,
                            network=network,
                            asset=asset,
                            amount_usd=amount_usd,
                            operation=operation,
                        )
                        # Settlement-success gating (fix #3): for self-facilitation
                        # (EIP-3009) funds only move at settle, so a verify that
                        # passes but a settle that FAILS must NOT grant access.
                        # Fail closed: reject with a fresh 402 challenge and never
                        # mark x402_verified.
                        if not settlement or settlement.get("success") is not True:
                            audit_event(
                                "x402_settle_failed_access_denied",
                                actor=caller_key,
                                path=path,
                                payment_id=payment_id,
                                reason=settlement.get("reason", "") if settlement else "",
                            )
                            logger.warning(
                                "x402_settle_failed_access_denied",
                                extra={
                                    "payment_id": payment_id,
                                    "tx_hash": tx_hash,
                                    "reason": settlement.get("reason", "") if settlement else "",
                                },
                            )
                            await self._send_payment_required(operation, path, send)
                            return
                        response_b64 = base64.b64encode(json.dumps(settlement).encode()).decode()

                        response_b64_bytes = response_b64.encode()

                        # Payment IS the credential (see pre-verified path).
                        scope["x402_verified"] = {
                            "payment_id": payment_id,
                            "caller": caller_key,
                            "operation": operation,
                            "tx_hash": tx_hash,
                        }

                        async def wrapped_send(message: dict[str, Any]) -> None:
                            if message["type"] == "http.response.start":
                                hdrs = list(message.get("headers", []))
                                hdrs.append((b"payment-response", response_b64_bytes))
                                message["headers"] = hdrs
                            await send(message)

                        await self.app(scope, receive, wrapped_send)
                        return
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("x402_payment_decode_failed", extra={"error": str(e)})

        await self._send_payment_required(operation, path, send)

    async def _send_payment_required(self, operation: str, path: str, send: Any) -> None:
        """Send a spec-compliant 402 Payment Required response.

        The challenge is built in multi-asset mode so agents see the full
        canonical acceptance surface (every SUPPORTED_ASSETS network/asset
        keyed by CAIP-2 network id) in the body. The PAYMENT-REQUIRED header
        is compacted under X402_PAYMENT_HEADER_MAX_BYTES — Cloudflare 502s
        any response with a larger single header, which broke every paid
        request through the public tunnel (2026-08-25 incident).
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
