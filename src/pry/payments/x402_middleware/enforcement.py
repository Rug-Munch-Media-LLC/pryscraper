"""x402 ASGI enforcement middleware (audit E41 split)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import base64
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pry.payments.x402 import (
    PAYMENT_VALIDITY_SECONDS,
    X402Handler,
    _encode_payment_required_body,
    validate_client_amount,
)
from pry.payments.x402_middleware import config as _pricing_config
from pry.payments.x402_middleware.classification import (
    DEFAULT_FREE_PATHS,
    DEFAULT_FREE_PREFIXES,
    _admin_prefix,
    _caller_key_from_scope,
    resolve_operation,
)
from pry.payments.x402_middleware.config import (
    X402_GATE_MISCONFIGURED,
)

logger = logging.getLogger(__name__)

# full acceptance surface; only the header is compacted under this budget.
X402_PAYMENT_HEADER_MAX_BYTES = 12_000


def _compact_payment_required_header(body: dict[str, Any], max_bytes: int) -> str:
    """Return a base64 PAYMENT-REQUIRED payload that fits ``max_bytes``.

    Pass 1 keeps ONE accept per network family (stablecoin preferred, e.g.
    USDC on solana:mainnet) — every chain stays payable-from-the-header,
    which is a documented agent-facing contract (see
    test_paid_endpoint_solana_tron_challenge_structure). 26 accepts shrink
    to ~8. Pass 2 drops networks from the tail only if still over budget.
    Always keeps at least one accept so the challenge stays valid for
    spec-compliant clients. The JSON body is never modified — it carries
    the full acceptance surface.
    """
    encoded = _encode_payment_required_body(body)
    if len(encoded.encode()) <= max_bytes:
        return encoded
    accepts = body.get("accepts") or []
    by_network: dict[str, dict[str, Any]] = {}
    ordered_networks: list[str] = []
    for a in accepts:
        net = a.get("network", "")
        if net not in by_network:
            by_network[net] = a
            ordered_networks.append(net)
        elif a.get("asset") in ("USDC", "USDT") and by_network[net].get("asset") not in (
            "USDC",
            "USDT",
        ):
            by_network[net] = a
    kept = [by_network[k] for k in ordered_networks]
    trimmed = {**body, "accepts": kept}
    encoded = _encode_payment_required_body(trimmed)
    while kept and len(encoded.encode()) > max_bytes:
        kept = kept[:-1]
        encoded = _encode_payment_required_body({**trimmed, "accepts": kept})
    if not kept:
        # Never emit an empty accepts array — fall back to the first entry.
        kept = accepts[:1]
        encoded = _encode_payment_required_body({**trimmed, "accepts": kept})
    logger.warning(
        "x402_payment_header_compacted",
        extra={
            "accepts_total": len(accepts),
            "accepts_in_header": len(kept),
            "header_bytes": len(encoded.encode()),
        },
    )
    return encoded


# Fail-closed gate firings (paid prefix without pricing). Prometheus-optional:
# the middleware must work without the metrics client installed.


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
        self.payments: dict[str, dict[str, Any]] = {}

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
        if self._is_free(path):
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

        headers = dict(scope.get("headers", []))
        payment_sig = headers.get(b"payment-signature", b"").decode()
        payment_id_header = headers.get(b"x-payment-id", b"").decode()
        batch_id_header = headers.get(b"x-batch-payment-id", b"").decode()

        # Check pre-verified individual payment (expiry + caller-bound).
        # Refresh first so payments issued by other handlers (e.g. the
        # /v1/x402/pay route) are visible to this middleware instance.
        if payment_id_header:
            self.handler.refresh()
            if self.handler.is_paid(payment_id_header, caller_key=caller_key):
                await self.app(scope, receive, send)
                return

        # Check pre-verified batch payment
        if batch_id_header:
            from pry.payments.x402 import is_batch_paid

            if is_batch_paid(batch_id_header):
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
                    # Server-side pricing is authoritative: never trust the
                    # client-supplied amount. Reject underpayment BEFORE any
                    # facilitator call. ``network`` lets the canonical
                    # SUPPORTED_ASSETS table quote non-1:1 assets correctly.
                    ok, price_reason = validate_client_amount(
                        operation, amount_usd, asset, network=network
                    )
                    if not ok:
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
                        response_b64 = base64.b64encode(json.dumps(settlement).encode()).decode()
                        self.payments[payment_id] = {
                            "payment_id": payment_id,
                            "tx_hash": tx_hash,
                            "caller_key": caller_key,
                            "expires_at": (
                                datetime.now(UTC) + timedelta(seconds=PAYMENT_VALIDITY_SECONDS)
                            ).isoformat(),
                            "verified_at": datetime.now(UTC).isoformat(),
                        }

                        response_b64_bytes = response_b64.encode()

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
