"""Pry — x402 scheme/offer/pricing helpers.

Owns the x402 enums, the server-side pricing table, atomic-unit conversion,
Base64 header codecs, network/asset compatibility mapping, the
spec-compliant ``build_payment_required`` builder, and the legacy (pre-spec)
payment-request helpers. Config constants (``X402_WALLET``,
``X402_DEFAULT_ASSET``, …) are imported from the package root.

Split into per-concern modules (behavior unchanged):

- :mod:`.enums` — payment schemes, networks, assets, decimals tables
- :mod:`.networks` — CAIP-2 resolution, acceptance tables, payTo resolution
- :mod:`.oracle` — USD price oracle (live + static fallback, cached)
- :mod:`.pricing` — server-side pricing, atomic conversion, 402 builders
- :mod:`.digest` — domain-separated keccak digest + header codecs
- :mod:`.attestation` — server attestation sign/verify over the 402 body
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pry.payments.x402 import (
    X402_NETWORK_WALLETS,
    X402_PLACEHOLDER_WALLETS,
    X402_WALLET,
)

from .attestation import (
    _attestation_private_key,
    _encode_payment_required_body,
    attest_payment_required,
    attestation_signer_address,
    attested_max_amount_required,
    verify_payment_required_attestation,
)
from .digest import (
    X402_ATTEST_ALGORITHM,
    X402_ATTEST_DOMAIN,
    X402_ATTEST_KEY_ENV,
    X402_ATTEST_MAX_AGE_SECONDS,
    X402_ATTEST_MAX_SKEW_SECONDS,
    X402_ATTEST_SECRET_ENV,
    X402_ATTEST_VERSION,
    _attestation_digest,
    _attestation_payload,
    _decode_payment_signature,
)
from .enums import (
    _NATIVE_ASSETS,
    _STABLECOIN_ASSETS,
    ASSET_DECIMALS,
    X402Asset,
    X402Network,
    X402Scheme,
)
from .networks import (
    CAIP2_NETWORK_IDS,
    SUPPORTED_ASSETS,
    SUPPORTED_NETWORKS,
    VERIFICATION_STATUS,
    _asset_on_network,
    _default_networks_for_asset,
    flatten_supported_assets,
    is_asset_supported,
    network_family,
    network_verification_status,
    normalize_network_id,
    resolve_asset_entry,
    resolve_pay_to,
    treasury_wallets,
)
from .oracle import (
    COINGECKO_ASSET_IDS,
    COINGECKO_SIMPLE_PRICE_URL,
    X402_ASSET_USD_PER_UNIT,
    X402_ORACLE_SOURCE,
    X402_ORACLE_TTL_SECONDS,
    X402_ORACLE_URL,
    AssetUsdQuote,
    _extract_usd_from_json,
    _fetch_oracle_price,
    _oracle_cache,
    clear_price_cache,
    get_asset_usd_price,
    oracle_source_label,
    probe_oracle,
)
from .pricing import (
    X402_PRICING,
    _legacy_payment_request,
    _public_base_url,
    _to_atomic,
    asset_to_atomic,
    build_multi_asset_accepts,
    build_payment_required,
    create_payment_request,
    require_payment_legacy,
    resolve_price_usd,
    usd_per_unit_for,
    validate_client_amount,
)


def negotiate_scheme(
    client_schemes: list[str] | None = None, network: str = "", asset: str = ""
) -> str:
    """Select best payment scheme based on client capabilities and network.

    Priority: exact-match > network-native > fallback to 'exact'.
    """
    if not client_schemes:
        return "exact"

    _native_map = {"eip155": "exact", "solana": "exact", "tron": "exact"}

    native = _native_map.get(network.split(":")[0], "exact") if network else "exact"

    if native in client_schemes:
        return native
    if "exact" in client_schemes:
        return "exact"
    return client_schemes[0] if client_schemes else "exact"


_IMMUTABLE_FIELDS = {"scheme", "network", "asset", "max_timeout_seconds"}
_RESERVED_EXTRA_KEYS = {"paymentFlow", "assetTransferMethod"}


def validate_scheme_extension(
    baseline: dict[str, Any], enriched: dict[str, Any], extension_key: str = ""
) -> str | None:
    """Validate that a scheme extension only enriches, never weakens. Returns None if OK, error string if violated."""
    if len(baseline.get("accepts", [])) != len(enriched.get("accepts", [])):
        return f"extension {extension_key} changed accepts length"
    for field in _IMMUTABLE_FIELDS:
        if baseline.get(field) != enriched.get(field):
            return f"extension {extension_key} modified immutable field: {field}"
    for key in _RESERVED_EXTRA_KEYS:
        if key in baseline.get("extra", {}) and key not in enriched.get("extra", {}):
            return f"extension {extension_key} removed reserved key: {key}"
    return None


def build_multi_payment_required(
    operation: str,
    resource: str,
    networks: list[dict[str, Any]] | None = None,
    amount_usd: float = 0.01,
) -> list[dict[str, Any]]:
    """Build payment requirements for multiple networks so payer can choose chain."""
    if not networks:
        networks = [
            {"network": "eip155:8453", "asset": "USDC", "address": ""},
            {"network": "solana:mainnet", "asset": "USDC", "address": ""},
            {"network": "tron:mainnet", "asset": "USDC", "address": ""},
        ]
    return [
        {
            "scheme": "exact",
            "network": net["network"],
            "asset": net["asset"],
            "amount": str(amount_usd),
            "payToAddress": net.get("address", ""),
            "resource": resource,
            "description": operation,
        }
        for net in networks
    ]


@dataclass
class PaymentInfo:
    """EIP-712 PaymentInfo for auth-capture escrow scheme."""

    payer: str
    payee: str
    amount_usd: float
    asset: str
    network: str
    pre_approval_expiry: int
    authorization_expiry: int
    refund_expiry: int
    min_fee_bps: int = 0
    max_fee_bps: int = 100
    capture_authorizer: str = ""

    def is_expired(self, ts: int = 0) -> bool:
        import time

        return (ts or int(time.time())) > self.authorization_expiry

    def can_refund(self, ts: int = 0) -> bool:
        import time

        return (ts or int(time.time())) > self.refund_expiry

    def validate_fee(self, fee_bps: int) -> bool:
        return self.min_fee_bps <= fee_bps <= self.max_fee_bps


# Mutable per-process cache of the resolved attestation key. Lives on the
# package (not a submodule) so tests that patch
# ``pry.payments.x402.scheme._attest_key_cache`` keep working after the
# module→package split; :func:`.attestation._attestation_private_key` reads
# and writes it here. Cleared on module reload (tests), so a reload + env
# change re-derives it. None = unconfigured.
_attest_key_cache: Any = None

__all__ = [
    "ASSET_DECIMALS",
    "CAIP2_NETWORK_IDS",
    "COINGECKO_ASSET_IDS",
    "COINGECKO_SIMPLE_PRICE_URL",
    "SUPPORTED_ASSETS",
    "SUPPORTED_NETWORKS",
    "VERIFICATION_STATUS",
    "X402_ASSET_USD_PER_UNIT",
    "X402_ATTEST_ALGORITHM",
    "X402_ATTEST_DOMAIN",
    "X402_ATTEST_KEY_ENV",
    "X402_ATTEST_MAX_AGE_SECONDS",
    "X402_ATTEST_MAX_SKEW_SECONDS",
    "X402_ATTEST_SECRET_ENV",
    "X402_ATTEST_VERSION",
    "X402_NETWORK_WALLETS",
    "X402_ORACLE_SOURCE",
    "X402_ORACLE_TTL_SECONDS",
    "X402_ORACLE_URL",
    "X402_PLACEHOLDER_WALLETS",
    "X402_PRICING",
    "X402_WALLET",
    "_NATIVE_ASSETS",
    "_STABLECOIN_ASSETS",
    "AssetUsdQuote",
    "PaymentInfo",
    "X402Asset",
    "X402Network",
    "X402Scheme",
    "_asset_on_network",
    "_attestation_digest",
    "_attestation_payload",
    "_attestation_private_key",
    "_decode_payment_signature",
    "_default_networks_for_asset",
    "_encode_payment_required_body",
    "_extract_usd_from_json",
    "_fetch_oracle_price",
    "_legacy_payment_request",
    "_oracle_cache",
    "_public_base_url",
    "_to_atomic",
    "asset_to_atomic",
    "attest_payment_required",
    "attestation_signer_address",
    "attested_max_amount_required",
    "build_multi_asset_accepts",
    "build_multi_payment_required",
    "build_payment_required",
    "clear_price_cache",
    "create_payment_request",
    "flatten_supported_assets",
    "get_asset_usd_price",
    "is_asset_supported",
    "negotiate_scheme",
    "network_family",
    "network_verification_status",
    "normalize_network_id",
    "oracle_source_label",
    "probe_oracle",
    "require_payment_legacy",
    "resolve_asset_entry",
    "resolve_pay_to",
    "resolve_price_usd",
    "treasury_wallets",
    "usd_per_unit_for",
    "validate_client_amount",
    "validate_scheme_extension",
    "verify_payment_required_attestation",
]
