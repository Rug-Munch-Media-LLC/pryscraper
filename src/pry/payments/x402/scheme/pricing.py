"""Pry — x402 server-side pricing, atomic conversion, and 402 builders."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import math
import os
import uuid
from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK

from .enums import _STABLECOIN_ASSETS, ASSET_DECIMALS, X402Asset, X402Network, X402Scheme
from .networks import (
    SUPPORTED_ASSETS,
    SUPPORTED_NETWORKS,
    VERIFICATION_STATUS,
    _asset_on_network,
    _default_networks_for_asset,
    flatten_supported_assets,
    network_family,
    normalize_network_id,
    resolve_asset_entry,
    resolve_pay_to,
)
from .oracle import X402_ASSET_USD_PER_UNIT

logger = logging.getLogger(__name__)


def _public_base_url() -> str:
    """Canonical public base URL for payment-manifest resource fields.

    Env override PRY_PUBLIC_BASE_URL; defaults to the production API.
    """
    return os.getenv("PRY_PUBLIC_BASE_URL", "https://api.pryscraper.com").rstrip("/")


# x402 pricing per operation (USDC atomic units, 6 decimals).
#
# Each entry may optionally carry a ``prices`` sub-table keyed by CAIP-2
# network id -> asset -> USD price, allowing per-network per-asset prices to
# override the base ``price_usd`` (see ``resolve_price_usd``). Example:
#   "scrape": {
#       "price_usd": 0.001,
#       "description": "Single URL scrape",
#       "prices": {"eip155:137": {"USDC": 0.0008}},  # cheaper on Polygon
#   }
X402_PRICING: dict[str, dict[str, Any]] = {
    "scrape": {"price_usd": 0.001, "description": "Single URL scrape"},
    "crawl": {"price_usd": 0.01, "description": "Crawl up to 10 pages"},
    "extract": {"price_usd": 0.005, "description": "Structured extraction"},
    "monitor": {"price_usd": 0.02, "description": "Create scheduled monitor"},
    "llm_call": {"price_usd": 0.01, "description": "LLM extraction call"},
    "template_execute": {"price_usd": 0.002, "description": "Execute scraper template"},
    "template_batch_execute": {"price_usd": 0.01, "description": "Execute up to 20 template items"},
    "browser_automation": {"price_usd": 0.05, "description": "Browser automation"},
    "bulk_crawl": {"price_usd": 0.10, "description": "Crawl up to 1000 pages"},
    "pdf_extract": {"price_usd": 0.01, "description": "PDF table extraction"},
    "ocr_extract": {"price_usd": 0.005, "description": "Image OCR"},
    "graphql_query": {"price_usd": 0.003, "description": "GraphQL query execution"},
    "schema_extract": {"price_usd": 0.002, "description": "Schema.org/JSON-LD extraction"},
}


def usd_per_unit_for(asset: str) -> float | None:
    """Return the USD value of one unit of ``asset`` (None when unknown)."""
    value = X402_ASSET_USD_PER_UNIT.get(asset.upper())
    if value is None or value <= 0:
        return None
    return value


def asset_to_atomic(
    amount_usd: float,
    asset: str = X402_DEFAULT_ASSET,
    network: str = "",
) -> int:
    """Convert a USD amount to atomic units for (network, asset).

    Uses the canonical SUPPORTED_ASSETS table when the pair is known so
    decimals and USD-per-unit come from one place; falls back to the legacy
    ASSET_DECIMALS table with 1:1 USD pricing for unknown pairs.
    """
    entry = resolve_asset_entry(network, asset)
    if entry:
        decimals = int(entry.get("decimals", ASSET_DECIMALS.get(asset.upper(), 6)))
    else:
        decimals = ASSET_DECIMALS.get(asset.upper(), 6)
    unit_usd = usd_per_unit_for(asset) or 1.0
    return round(amount_usd / unit_usd * (10**decimals))


def _to_atomic(amount_usd: float, asset: str = X402_DEFAULT_ASSET) -> int:
    """Convert USD amount to atomic units for the given asset."""
    decimals = ASSET_DECIMALS.get(asset, 6)
    return int(amount_usd * (10**decimals))


def resolve_price_usd(
    operation: str,
    network: str = "",
    asset: str = "",
) -> float:
    """Return the SERVER-side authoritative price (USD) for an operation.

    Never trust a client-supplied ``amount_usd``: this is the number the
    server enforces. Returns 0.0 for unknown operations (callers must decide
    how to treat those).

    When ``network`` (legacy name or CAIP-2 id) and ``asset`` are supplied, a
    per-network/per-asset override in ``X402_PRICING[operation]["prices"]``
    takes precedence; otherwise the operation's base ``price_usd`` applies.
    """
    info = X402_PRICING.get(operation) or {}
    if network and asset:
        network_id = normalize_network_id(network)
        raw_prices = info.get("prices")
        prices = raw_prices if isinstance(raw_prices, dict) else {}
        raw_network_prices = prices.get(network_id)
        network_prices = raw_network_prices if isinstance(raw_network_prices, dict) else {}
        override = network_prices.get(asset.upper())
        if override is not None:
            return float(override)
    return float(info.get("price_usd", 0.0))


def validate_client_amount(
    operation: str,
    client_amount_usd: float,
    asset: str = X402_DEFAULT_ASSET,
    network: str = "",
) -> tuple[bool, str]:
    """Reject client-supplied underpayment against the server-side price.

    Comparison happens in atomic units so float drift cannot be exploited.
    Returns ``(ok, reason)``. ``ok=False`` means the client offered LESS than
    the authoritative price (or a non-finite/negative amount) — the payment
    must be refused. Overpayment is allowed (client may pay more).

    When ``network`` is given and the (network, asset) pair is in the
    canonical SUPPORTED_ASSETS table, the table's decimals and USD-per-unit
    conversion are used (so non-1:1 assets like ETH/ARB quote correctly);
    otherwise the legacy 1:1 ASSET_DECIMALS path is used.
    """
    if client_amount_usd is None or not math.isfinite(float(client_amount_usd)):
        return False, "invalid (non-finite) client amount"
    if client_amount_usd < 0:
        return False, f"negative client amount {client_amount_usd}"
    required = resolve_price_usd(operation, network=network, asset=asset)
    if required <= 0:
        # No server price configured for this operation — nothing to enforce.
        return True, ""
    try:
        if resolve_asset_entry(network, asset) is not None:
            required_atomic = asset_to_atomic(required, asset, network)
            client_atomic = asset_to_atomic(client_amount_usd, asset, network)
        else:
            required_atomic = _to_atomic(required, asset)
            client_atomic = _to_atomic(client_amount_usd, asset)
    except (ValueError, TypeError):
        return False, "invalid amount/asset for pricing check"
    if client_atomic < required_atomic:
        return (
            False,
            f"underpayment: client supplied {client_amount_usd} USD, "
            f"server requires {required} USD for '{operation}'",
        )
    return True, ""


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


# These return the pre-spec response format. Prefer the spec-compliant methods
# above in new code.


def _legacy_payment_request(
    operation: str,
    metadata: dict[str, Any] | None = None,
    price_usd: float = 0.001,
    payment_id: str = "",
) -> dict[str, Any]:
    price_info = X402_PRICING.get(operation, {"price_usd": price_usd, "description": operation})
    return {
        "x402Version": 1,
        "payment_id": payment_id or uuid.uuid4().hex[:12],
        "scheme": X402Scheme.EXACT.value,
        "network": X402_DEFAULT_NETWORK,
        "resource": f"https://pry.dev/api/{operation}",
        "operation": operation,
        "description": price_info.get("description", operation),
        "maxAmountRequired": str(int(price_info["price_usd"] * 1_000_000)),
        "asset": X402Asset.USDC.value,
        "payTo": resolve_pay_to(X402_DEFAULT_NETWORK),
        "maxTimeoutSeconds": 60,
        "extra": metadata or {},
    }


def create_payment_request(
    operation: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Legacy: build a single-payment payment request dict.

    Returns the pre-spec shape used by /v1/x402/payment.
    """
    if operation not in X402_PRICING:
        return {"error": f"Unknown operation: {operation}"}
    req = _legacy_payment_request(operation, metadata=metadata)
    logger.info(
        "x402_payment_request_created",
        extra={"payment_id": req["payment_id"], "operation": operation},
    )
    return req


def require_payment_legacy(
    operation: str, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Legacy: build the pre-spec 402 response with X-Payment-Required header."""
    if operation not in X402_PRICING:
        return {"error": f"Unknown operation: {operation}"}
    return {
        "status_code": 402,
        "headers": {
            "X-Payment-Required": "true",
            "X-Payment-Options": "x402",
        },
        "body": {
            "error": "Payment Required",
            "x402": _legacy_payment_request(operation, metadata=metadata),
            "instructions": (
                "Send USDC payment to the wallet address, then call the API again "
                "with the X-Payment-Hash header."
            ),
        },
    }
