"""Pry — X402Handler 402 response generation (extracted from ``handler.py``).

Builds spec-compliant x402 payment-required responses (body + headers) and
records the challenge metric. Mixed into
:class:`~pry.payments.x402.handler.X402Handler` as ``ResponseMixin``.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pry.payments.x402 import X402_DEFAULT_NETWORK
from pry.payments.x402.metrics import record_challenge
from pry.payments.x402.scheme import (
    _encode_payment_required_body,
    build_payment_required,
)


class ResponseMixin:
    """Spec-compliant 402 response builders for the x402 handler."""

    def create_payment_required(
        self,
        operation: str,
        resource: str = "",
        description: str = "",
        accepts: list[dict[str, Any]] | None = None,
        preferred_networks: list[str] | None = None,
        preferred_assets: list[str] | None = None,
        multi_asset: bool = False,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Create a spec-compliant x402 payment request.

        Returns: (body_dict, headers_dict)
        - body_dict: the JSON body for the 402 response
        - headers_dict: the HTTP headers to include (PAYMENT-REQUIRED Base64-encoded)

        ``multi_asset=True`` builds options from the canonical
        SUPPORTED_ASSETS table (CAIP-2 network ids + every quotable asset)
        and attaches the supported_assets/networks tables to the body so
        clients see the full multi-chain acceptance surface. The default
        (False) keeps the V1 legacy single-asset shape.
        """
        body = build_payment_required(
            operation,
            resource,
            accepts,
            description,
            preferred_networks=preferred_networks,
            preferred_assets=preferred_assets,
            multi_asset=multi_asset,
        )
        headers = {
            "PAYMENT-REQUIRED": _encode_payment_required_body(body),
            "X-Payment-Required": "true",
            "X-Payment-Options": "x402",
        }
        record_challenge(operation, X402_DEFAULT_NETWORK)
        return body, headers

    def require_payment(
        self,
        operation: str,
        resource: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        """Build a complete 402 response with proper headers.

        Returns: {"status_code": 402, "headers": {...}, "body": {...}}
        """
        body, headers = self.create_payment_required(operation, resource, description)
        return {
            "status_code": 402,
            "headers": headers,
            "body": body,
        }
