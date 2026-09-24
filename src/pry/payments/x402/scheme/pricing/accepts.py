"""Multi-asset x402 acceptance-table construction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from ..enums import _STABLECOIN_ASSETS, X402Scheme
from ..networks import (
    SUPPORTED_ASSETS,
    VERIFICATION_STATUS,
    network_family,
    normalize_network_id,
    resolve_pay_to,
)
from .catalog import (
    X402_PRICING,
    _public_base_url,
    asset_to_atomic,
    resolve_price_usd,
    usd_per_unit_for,
)


def build_multi_asset_accepts(
    operation: str,
    resource: str = "",
    description: str = "",
    mime_type: str = "application/json",
    preferred_networks: list[str] | None = None,
    preferred_assets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the accepts list covering every quotable asset in SUPPORTED_ASSETS.

    Each option is keyed by CAIP-2 network id and quotes the USD-equivalent
    atomic amount for the operation's server-side price (per-network
    ``prices`` overrides in X402_PRICING apply). Assets without a configured
    USD-per-unit conversion are skipped — they cannot be quoted honestly.

    ``preferred_networks``/``preferred_assets`` narrow the acceptance surface
    to the requested networks/assets (as legacy names or CAIP-2 ids). When
    omitted, the full SUPPORTED_ASSETS table is advertised.
    """
    pref_networks = {normalize_network_id(n) for n in (preferred_networks or []) if n}
    pref_assets = {a.upper() for a in (preferred_assets or []) if a}
    price_info = X402_PRICING.get(operation, {"price_usd": 0.001, "description": operation})
    resource_url = resource or f"{_public_base_url()}/api/{operation}"
    accepts: list[dict[str, Any]] = []
    for network_id, assets in SUPPORTED_ASSETS.items():
        if pref_networks and network_id not in pref_networks:
            continue
        # Gate on verification status: only advertise networks whose
        # settlement verification is REAL (VERIFICATION_STATUS[family]["real"]).
        # Scaffolded families (e.g. TRON — no TRC-20 verifier wired) must not
        # appear in the 402 acceptance table, or clients could attempt
        # payments that can never settle.
        family = network_family(network_id)
        verification = VERIFICATION_STATUS.get(family, {})
        if not verification.get("real", False):
            continue
        for asset, entry in assets.items():
            if pref_assets and asset.upper() not in pref_assets:
                continue
            price_usd = resolve_price_usd(operation, network=network_id, asset=asset)
            unit_usd = usd_per_unit_for(asset)
            if not unit_usd or price_usd <= 0:
                continue
            amount = asset_to_atomic(price_usd, asset, network_id)
            pay_to = resolve_pay_to(network_id)  # family-aware; "" when unconfigured
            accepts.append(
                {
                    "scheme": X402Scheme.EXACT.value,
                    "network": network_id,
                    "maxAmountRequired": str(amount),
                    "resource": resource_url,
                    "description": description or price_info.get("description", operation),
                    "mimeType": mime_type,
                    "payToAddress": pay_to,
                    "asset": asset,
                    "extra": {
                        "name": entry.get("name", asset),
                        "version": "2",
                        "operation": operation,
                        "caip2": network_id,
                        "verification": entry.get("verification", ""),
                        "contract": entry.get("contract", ""),
                        "decimals": entry.get("decimals", 6),
                        "priceUsd": price_usd,
                        "usdPerUnit": unit_usd,
                        "usdPerUnitSource": (
                            "stablecoin" if asset in _STABLECOIN_ASSETS else "static-default"
                        ),
                    },
                }
            )
    return accepts
