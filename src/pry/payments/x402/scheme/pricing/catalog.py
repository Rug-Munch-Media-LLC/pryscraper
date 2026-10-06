"""Server-side x402 pricing catalog and validation."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import math
import os
from typing import Any

from pry.payments.x402 import X402_DEFAULT_ASSET

from ..enums import ASSET_DECIMALS
from ..networks import normalize_network_id, resolve_asset_entry
from ..oracle import X402_ASSET_USD_PER_UNIT

logger = logging.getLogger(__name__)


def _public_base_url() -> str:
    """Canonical public base URL for payment-manifest resource fields.

    Env override PRY_PUBLIC_BASE_URL; defaults to the production API.
    """
    return os.getenv("PRY_PUBLIC_BASE_URL", "https://api.pryscraper.com").rstrip("/")


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
    except (ValueError, TypeError) as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "validate_client_amount"},
        )
        return False, "invalid amount/asset for pricing check"
    if client_atomic < required_atomic:
        return (
            False,
            f"underpayment: client supplied {client_amount_usd} USD, "
            f"server requires {required} USD for '{operation}'",
        )
    return True, ""


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
