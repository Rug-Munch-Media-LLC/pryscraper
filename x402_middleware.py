"""Pry — x402 (HTTP 402 Payment Required) Middleware.
FastAPI/ASGI middleware that gates endpoints behind x402 payments per the
x402 v1 spec from https://github.com/coinbase/x402.

Implements the spec-compliant flow:
- Read the ``PAYMENT-SIGNATURE`` header (Base64-encoded JSON of the signed
  payment payload: ``{"payment_id": "...", "tx_hash": "..."}``).
- On a missing or invalid payment, return ``402 Payment Required`` with the
  ``PAYMENT-REQUIRED`` header (Base64-encoded ``PaymentRequired`` body).
- On a valid payment, call the downstream app and add a ``PAYMENT-RESPONSE``
  header (Base64-encoded settlement receipt) to the response.

Usage: app.add_middleware(X402Middleware, free_paths=["/health", "/v1/templates"])
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import base64
import json
import logging
from datetime import UTC, datetime
from typing import Any

from x402 import X402_PRICING, X402Handler

logger = logging.getLogger(__name__)

PAID_ENDPOINTS = {
    "/v1/scrape": "scrape",
    "/v1/crawl": "crawl",
    "/v1/extract/css": "extract",
    "/v1/extract/llm": "llm_call",
    "/v1/templates/execute": "template_execute",
    "/v1/templates/batch": "template_batch_execute",
    "/v1/automate": "browser_automation",
    "/v1/monitor": "monitor",
    "/v1/pdf/extract": "pdf_extract",
}


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
        wallet: str = "pry-default",
        network: str = "base",
        facilitator_url: str = "https://x402.org/facilitator",
    ) -> None:
        self.app = app
        self.free_paths = set(
            free_paths or ["/health", "/live", "/ready", "/docs", "/openapi.json"]
        )
        self.wallet = wallet
        self.network = network
        self.facilitator_url = facilitator_url
        self.handler = X402Handler(wallet=wallet, facilitator_url=facilitator_url)
        self.payments: dict[str, dict[str, Any]] = {}

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.free_paths or not any(path.startswith(p) for p in PAID_ENDPOINTS):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        payment_sig = headers.get(b"payment-signature", b"").decode()
        payment_id_header = headers.get(b"x-payment-id", b"").decode()
        batch_id_header = headers.get(b"x-batch-payment-id", b"").decode()

        # Check pre-verified individual payment
        if payment_id_header and self.handler.is_paid(payment_id_header):
            await self.app(scope, receive, send)
            return

        # Check pre-verified batch payment
        if batch_id_header:
            from x402 import is_batch_paid

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
                    verify_result = await self.handler.verify_payment(
                        payment_id, tx_hash, network=network, asset=asset, amount_usd=amount_usd
                    )
                    if verify_result.get("verified"):
                        settlement = await self.handler.settle_payment(
                            payment_id, tx_hash, network=network, asset=asset, amount_usd=amount_usd
                        )
                        response_b64 = base64.b64encode(json.dumps(settlement).encode()).decode()
                        self.payments[payment_id] = {
                            "payment_id": payment_id,
                            "tx_hash": tx_hash,
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
                logger.warning("x402_payment_decode_failed err=%s", e)

        operation = next((op for ep, op in PAID_ENDPOINTS.items() if path.startswith(ep)), None)
        if not operation or operation not in X402_PRICING:
            await self.app(scope, receive, send)
            return

        body, x402_headers = self.handler.create_payment_required(operation, resource=path)
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
