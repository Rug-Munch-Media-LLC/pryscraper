"""Spec-compliant x402 PaymentRequired response construction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET

from ..networks import SUPPORTED_NETWORKS, flatten_supported_assets
from .accepts import build_multi_asset_accepts
from .catalog import X402_PRICING, _public_base_url, _to_atomic
from .challenge import build_challenge
from .context import AcceptRequest
from .legacy_accepts import build_legacy_accepts


def build_payment_required(
    operation: str,
    resource: str = "",
    accepts: list[dict[str, Any]] | None = None,
    description: str = "",
    mime_type: str = "application/json",
    preferred_networks: list[str] | None = None,
    preferred_assets: list[str] | None = None,
    multi_asset: bool = False,
) -> dict[str, Any]:
    """Build a spec-compliant x402 PaymentRequired response.

    Returns a dict that should be:
    1. Returned as the body of the 402 response (JSON)
    2. Base64-encoded and put in the PAYMENT-REQUIRED header

    Args:
        operation: The operation being paid for (e.g., "scrape")
        resource: Full URL of the protected resource
        accepts: List of payment options (if None, generates defaults)
        description: Human-readable description
        mime_type: Expected response MIME type
        preferred_networks: Networks to prioritize in accepts
        preferred_assets: Assets to prioritize in accepts
        multi_asset: When True (and ``accepts`` is None) build options from
            the canonical SUPPORTED_ASSETS table — every quotable
            network/asset keyed by CAIP-2 network id — and attach the
            supported_assets/networks tables to the body so clients see the
            full multi-chain acceptance surface. Default False keeps the V1
            legacy single-asset shape.
    """
    price_info = X402_PRICING.get(operation, {"price_usd": 0.001, "description": operation})
    amount_atomic = _to_atomic(price_info["price_usd"], X402_DEFAULT_ASSET)
    resource_url = resource or f"{_public_base_url()}/api/{operation}"

    if accepts is None:
        req = AcceptRequest(
            operation=operation,
            price_info=price_info,
            resource_url=resource_url,
            description=description,
            mime_type=mime_type,
            amount_atomic=amount_atomic,
            preferred_networks=preferred_networks,
            preferred_assets=preferred_assets,
        )
        accepts = _default_accepts(req, multi_asset)

    body: dict[str, Any] = {"x402Version": 1, "accepts": accepts}
    body.update(build_challenge(accepts, description, operation, price_info))
    if multi_asset:
        body["networks"] = SUPPORTED_NETWORKS
        body["supported_assets"] = flatten_supported_assets()
    return body


def _default_accepts(req: AcceptRequest, multi_asset: bool) -> list[dict[str, Any]]:
    """Build the default accepts list when the caller supplies none."""
    if multi_asset:
        return build_multi_asset_accepts(
            req.operation,
            resource=req.resource_url,
            description=req.description,
            mime_type=req.mime_type,
            preferred_networks=req.preferred_networks,
            preferred_assets=req.preferred_assets,
        )
    return build_legacy_accepts(req)
