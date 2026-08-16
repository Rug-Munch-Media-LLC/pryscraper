"""Pry — x402 scheme/offer/pricing helpers.

Owns the x402 enums, the server-side pricing table, atomic-unit conversion,
Base64 header codecs, network/asset compatibility mapping, the
spec-compliant ``build_payment_required`` builder, and the legacy (pre-spec)
payment-request helpers. Config constants (``X402_WALLET``,
``X402_DEFAULT_ASSET``, …) are imported from the package root.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import base64
import json
import logging
import math
import uuid
from enum import StrEnum
from typing import Any, cast

from x402 import X402_DEFAULT_ASSET, X402_DEFAULT_NETWORK, X402_WALLET

logger = logging.getLogger(__name__)

# x402 pricing per operation (USDC atomic units, 6 decimals)
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


class X402Scheme(StrEnum):
    """Payment schemes supported by x402."""

    EXACT = "exact"
    UPTO = "upto"


class X402Network(StrEnum):
    """Blockchain networks supported by x402."""

    BASE = "base"
    SOLANA = "solana"
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BNB = "bnb"
    AVALANCHE = "avalanche"
    BASE_SEPOLIA = "base-sepolia"
    TRON = "tron"
    BITCOIN = "bitcoin"
    LITECOIN = "litecoin"
    DOGECOIN = "dogecoin"


class X402Asset(StrEnum):
    """Token assets supported by x402."""

    USDC = "USDC"
    USDT = "USDT"
    DAI = "DAI"
    ETH = "ETH"
    SOL = "SOL"
    MATIC = "MATIC"
    TRX = "TRX"
    BTC = "BTC"
    LTC = "LTC"
    DOGE = "DOGE"


# Native assets that settle via plain value transfers on the EIP-7702 RPCs.
_NATIVE_ASSETS = {X402Asset.ETH.value}

# Asset decimals for atomic conversion
ASSET_DECIMALS: dict[str, int] = {
    X402Asset.USDC.value: 6,
    X402Asset.USDT.value: 6,
    X402Asset.DAI.value: 18,
    X402Asset.ETH.value: 18,
    X402Asset.SOL.value: 9,
    X402Asset.MATIC.value: 18,
    X402Asset.TRX.value: 6,
    X402Asset.BTC.value: 8,
    X402Asset.LTC.value: 8,
    X402Asset.DOGE.value: 8,
}


def _to_atomic(amount_usd: float, asset: str = X402_DEFAULT_ASSET) -> int:
    """Convert USD amount to atomic units for the given asset."""
    decimals = ASSET_DECIMALS.get(asset, 6)
    return int(amount_usd * (10**decimals))


def _from_atomic(amount_atomic: int, asset: str = X402_DEFAULT_ASSET) -> float:
    """Convert atomic units back to USD-normalized float."""
    decimals = ASSET_DECIMALS.get(asset, 6)
    return float(round(amount_atomic / (10**decimals), decimals))


def _encode_payment_required_body(body: dict[str, Any]) -> str:
    """Base64-encode the PaymentRequired body per x402 spec."""
    return base64.b64encode(json.dumps(body).encode()).decode()


def _decode_payment_signature(header: str) -> dict[str, Any] | None:
    """Decode the PAYMENT-SIGNATURE header per x402 spec."""
    try:
        return cast("dict[str, Any]", json.loads(base64.b64decode(header).decode()))
    except (ValueError, OSError):
        return None


def _encode_payment_response(settlement: dict[str, Any]) -> str:
    """Base64-encode the PaymentResponse (settlement receipt) per x402 spec."""
    return base64.b64encode(json.dumps(settlement).encode()).decode()


def _default_networks_for_asset(asset: str) -> list[str]:
    """Return sensible default networks for an asset."""
    asset = asset.upper()
    mapping: dict[str, list[str]] = {
        X402Asset.USDC.value: [
            X402Network.BASE.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
            X402Network.SOLANA.value,
            X402Network.ETHEREUM.value,
            X402Network.BNB.value,
            X402Network.AVALANCHE.value,
        ],
        X402Asset.USDT.value: [
            X402Network.ETHEREUM.value,
            X402Network.BNB.value,
            X402Network.TRON.value,
            X402Network.SOLANA.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
            X402Network.AVALANCHE.value,
        ],
        X402Asset.DAI.value: [
            X402Network.ETHEREUM.value,
            X402Network.POLYGON.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.BASE.value,
        ],
        X402Asset.ETH.value: [
            X402Network.ETHEREUM.value,
            X402Network.BASE.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
        ],
        X402Asset.SOL.value: [X402Network.SOLANA.value],
        X402Asset.MATIC.value: [X402Network.POLYGON.value],
        X402Asset.TRX.value: [X402Network.TRON.value],
        X402Asset.BTC.value: [X402Network.BITCOIN.value],
        X402Asset.LTC.value: [X402Network.LITECOIN.value],
        X402Asset.DOGE.value: [X402Network.DOGECOIN.value],
    }
    return mapping.get(asset, [X402Network.BASE.value])


def _asset_on_network(asset: str, network: str) -> bool:
    """Check whether an asset is generally supported on a network."""
    return network in _default_networks_for_asset(asset)


def resolve_price_usd(operation: str) -> float:
    """Return the SERVER-side authoritative price (USD) for an operation.

    Never trust a client-supplied ``amount_usd``: this is the number the
    server enforces. Returns 0.0 for unknown operations (callers must decide
    how to treat those).
    """
    return float(X402_PRICING.get(operation, {}).get("price_usd", 0.0))


def validate_client_amount(
    operation: str,
    client_amount_usd: float,
    asset: str = X402_DEFAULT_ASSET,
) -> tuple[bool, str]:
    """Reject client-supplied underpayment against the server-side price.

    Comparison happens in atomic units so float drift cannot be exploited.
    Returns ``(ok, reason)``. ``ok=False`` means the client offered LESS than
    the authoritative price (or a non-finite/negative amount) — the payment
    must be refused. Overpayment is allowed (client may pay more).
    """
    if client_amount_usd is None or not math.isfinite(float(client_amount_usd)):
        return False, "invalid (non-finite) client amount"
    if client_amount_usd < 0:
        return False, f"negative client amount {client_amount_usd}"
    required = resolve_price_usd(operation)
    if required <= 0:
        # No server price configured for this operation — nothing to enforce.
        return True, ""
    try:
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


def build_payment_required(
    operation: str,
    resource: str = "",
    accepts: list[dict[str, Any]] | None = None,
    description: str = "",
    mime_type: str = "application/json",
    preferred_networks: list[str] | None = None,
    preferred_assets: list[str] | None = None,
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
    """
    price_info = X402_PRICING.get(operation, {"price_usd": 0.001, "description": operation})
    amount_atomic = _to_atomic(price_info["price_usd"], X402_DEFAULT_ASSET)
    resource_url = resource or f"https://pry.dev/api/{operation}"

    if accepts is None:
        networks = preferred_networks or _default_networks_for_asset(X402_DEFAULT_ASSET)
        assets = preferred_assets or [X402_DEFAULT_ASSET]
        accepts = []
        for network in networks:
            for asset in assets:
                if not _asset_on_network(asset, network):
                    continue
                amount = _to_atomic(price_info["price_usd"], asset)
                accepts.append(
                    {
                        "scheme": X402Scheme.EXACT.value,
                        "network": network,
                        "maxAmountRequired": str(amount),
                        "resource": resource_url,
                        "description": description or price_info.get("description", operation),
                        "mimeType": mime_type,
                        "payToAddress": X402_WALLET,
                        "asset": asset,
                        "extra": {"name": asset, "version": "2", "operation": operation},
                    }
                )
        if not accepts:
            # Final fallback so we never return an empty accepts array
            accepts.append(
                {
                    "scheme": X402Scheme.EXACT.value,
                    "network": X402Network.BASE.value,
                    "maxAmountRequired": str(amount_atomic),
                    "resource": resource_url,
                    "description": description or price_info.get("description", operation),
                    "mimeType": mime_type,
                    "payToAddress": X402_WALLET,
                    "asset": X402_DEFAULT_ASSET,
                    "extra": {"name": X402_DEFAULT_ASSET, "version": "2", "operation": operation},
                }
            )

    return {
        "x402Version": 1,
        "accepts": accepts,
    }


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
        "payTo": X402_WALLET,
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
