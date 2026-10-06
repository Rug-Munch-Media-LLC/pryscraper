"""Legacy single-asset x402 acceptance-list construction (V1 shape)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pry.payments.x402 import X402_DEFAULT_ASSET

from ..enums import X402Network, X402Scheme
from ..networks import (
    VERIFICATION_STATUS,
    _asset_on_network,
    _default_networks_for_asset,
    network_family,
    resolve_pay_to,
)
from .catalog import _to_atomic

if TYPE_CHECKING:
    from .context import AcceptRequest


def build_legacy_accepts(req: AcceptRequest) -> list[dict[str, Any]]:
    """Build the V1 single-asset accepts list, never returning an empty list.

    Only networks whose settlement verification is REAL are advertised —
    scaffolded families (e.g. TRON) are skipped. A BASE-asset fallback option
    is appended when no network/asset pair qualifies, so callers always get a
    non-empty acceptance surface.
    """
    operation = req.operation
    price_info = req.price_info
    resource_url = req.resource_url
    description = req.description
    mime_type = req.mime_type
    networks = req.preferred_networks or _default_networks_for_asset(X402_DEFAULT_ASSET)
    assets = req.preferred_assets or [X402_DEFAULT_ASSET]
    accepts: list[dict[str, Any]] = []
    for network in networks:
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
    if accepts:
        return accepts
    # Final fallback so we never return an empty accepts array.
    fallback_pay_to = resolve_pay_to(X402Network.BASE.value)
    return [
        {
            "scheme": X402Scheme.EXACT.value,
            "network": X402Network.BASE.value,
            "maxAmountRequired": str(req.amount_atomic),
            "resource": resource_url,
            "description": description or price_info.get("description", operation),
            "mimeType": mime_type,
            "payToAddress": fallback_pay_to,
            "asset": X402_DEFAULT_ASSET,
            "extra": {"name": X402_DEFAULT_ASSET, "version": "2", "operation": operation},
        }
    ]
