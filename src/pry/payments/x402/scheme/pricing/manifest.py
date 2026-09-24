"""Spec-compliant x402 PaymentRequired response construction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK

from ..enums import X402Network, X402Scheme
from ..networks import (
    SUPPORTED_NETWORKS,
    VERIFICATION_STATUS,
    _asset_on_network,
    _default_networks_for_asset,
    flatten_supported_assets,
    network_family,
    resolve_pay_to,
)
from .accepts import build_multi_asset_accepts
from .catalog import X402_PRICING, _public_base_url, _to_atomic


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
        if multi_asset:
            accepts = build_multi_asset_accepts(
                operation,
                resource=resource_url,
                description=description,
                mime_type=mime_type,
                preferred_networks=preferred_networks,
                preferred_assets=preferred_assets,
            )
        else:
            networks = preferred_networks or _default_networks_for_asset(X402_DEFAULT_ASSET)
            assets = preferred_assets or [X402_DEFAULT_ASSET]
            accepts = []
            for network in networks:
                # Same real-verification gate as the multi-asset table:
                # scaffolded families (e.g. TRON) are never advertised.
                if not VERIFICATION_STATUS.get(network_family(network), {}).get("real", False):
                    continue
                for asset in assets:
                    if not _asset_on_network(asset, network):
                        continue
                    amount = _to_atomic(price_info["price_usd"], asset)
                    pay_to = resolve_pay_to(network)  # family-aware; "" when unconfigured
                    accepts.append(
                        {
                            "scheme": X402Scheme.EXACT.value,
                            "network": network,
                            "maxAmountRequired": str(amount),
                            "resource": resource_url,
                            "description": description or price_info.get("description", operation),
                            "mimeType": mime_type,
                            "payToAddress": pay_to,
                            "asset": asset,
                            "extra": {"name": asset, "version": "2", "operation": operation},
                        }
                    )
        if not accepts:
            # Final fallback so we never return an empty accepts array
            fallback_pay_to = resolve_pay_to(X402Network.BASE.value)
            accepts.append(
                {
                    "scheme": X402Scheme.EXACT.value,
                    "network": X402Network.BASE.value,
                    "maxAmountRequired": str(amount_atomic),
                    "resource": resource_url,
                    "description": description or price_info.get("description", operation),
                    "mimeType": mime_type,
                    "payToAddress": fallback_pay_to,
                    "asset": X402_DEFAULT_ASSET,
                    "extra": {"name": X402_DEFAULT_ASSET, "version": "2", "operation": operation},
                }
            )

    body: dict[str, Any] = {
        "x402Version": 1,
        "accepts": accepts,
    }
    # Self-documenting 402 (audit: challenge quality): an AI agent receiving
    # this body must understand exactly WHAT to pay, WHERE, and HOW without
    # reading docs. ``description`` is human+machine readable; ``instructions``
    # spells out the pay-then-retry flow with a concrete example from the
    # first accept; ``error`` carries the actionable message.
    first = accepts[0] if accepts else {}
    first_amount = str(first.get("maxAmountRequired", ""))
    first_asset = str(first.get("asset", X402_DEFAULT_ASSET))
    first_network = str(first.get("network", X402_DEFAULT_NETWORK))
    first_pay_to = str(first.get("payToAddress", ""))
    body["description"] = description or price_info.get("description", operation)
    body["instructions"] = (
        f"payment required: send {first_amount} {first_asset} "
        f"(atomic units) to {first_pay_to or '<configured treasury>'} on the "
        f"{first_network} network, then retry this request with the "
        f"PAYMENT-SIGNATURE header containing the payment_id and tx_hash. "
        f"See GET /v1/x402/pricing for the full price list and treasuries."
    )
    body["error"] = (
        f"payment required: send {first_amount} {first_asset} to "
        f"{first_pay_to or '<configured treasury>'} on {first_network}"
    )
    if multi_asset:
        # Multi-chain acceptance surface so agents can see every network/asset
        # they may pay with (additive — spec clients ignore unknown keys).
        body["networks"] = SUPPORTED_NETWORKS
        body["supported_assets"] = flatten_supported_assets()
    return body
