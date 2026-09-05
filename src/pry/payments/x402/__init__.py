"""Pry — x402 (HTTP 402 Payment Required) protocol implementation.

Implements the x402 v1 spec from https://github.com/coinbase/x402

This package was split out of the original ``x402.py`` god module. The
secrets/env-backed configuration lives in ``x402._config``; the package
``__init__`` reloads that module so ``importlib.reload(x402)`` recomputes
constants such as ``X402_WALLET`` when tests patch
``secrets_backend.get_secret``. Domain code lives in:

- ``x402.scheme``      — scheme/offer/pricing helpers (+ legacy payment requests)
- ``x402.facilitator`` — FacilitatorRouter + EIP-7702 self-verify
- ``x402.handler``     — X402Handler (verify/settle orchestration)
- ``x402.batch``       — batch payment helpers
- ``x402.solana_verifier`` — Solana SPL USDC on-chain verifier (getTransaction
  jsonParsed, httpx + stdlib — no Solana SDK)

The public import surface is unchanged: ``from pry.payments.x402 import X`` still works
(every public name is re-exported below), and ``x402.py`` remains as a thin
re-export facade.

Standards compliance:
- HTTP 402 status code with PaymentRequired body
- PAYMENT-REQUIRED header (Base64-encoded JSON)
- PAYMENT-SIGNATURE header (Base64-encoded JSON, signed)
- PAYMENT-RESPONSE header on success (Base64-encoded settlement receipt)

Server attestation (audit #1): the PAYMENT-REQUIRED body is now signed by the
server over the canonical (payTo, amount, network, nonce, issued_at, operation)
of every accept (``keccak256-ecdsa-secp256k1-v1``, x402/scheme.py). The signer
key comes from ``PRY_X402_ATTEST_KEY``, else ``PRY_X402_FACILITATOR_KEY``, else
is derived from ``PRY_X402_ATTEST_SECRET`` (never hardcoded); when none is
configured the body is emitted UNATTESTED (backward compatible). A client or a
verify/settle path validates the payTo with
``verify_payment_required_attestation(body, expected_signer=...)`` — see that
helper's docstring for the ``attested``/``verified`` semantics and the
out-of-band ``expected_signer`` trust requirement.
- Multi-chain support: base, solana, ethereum, polygon, arbitrum, optimism, bnb,
  avalanche, base-sepolia, tron, bitcoin, litecoin, dogecoin
- Multi-asset: USDC, USDT, native
- Canonical multi-asset acceptance table (``SUPPORTED_ASSETS``) keyed by
  CAIP-2 network id + asset: EVM ERC-20 (USDC/USDT/ETH/ARB/WETH), Solana SPL
  (USDC/USDT/SOL), TRON TRC-20 (USDT/TRX). EVM settlement verification is
  real (EIP-7702 self-verify + facilitators); Solana is real too (SPL RPC
  verifier — getTransaction jsonParsed USDC transferChecked); TRON is a
  [REVIEW] scaffold (structure/price/asset validation only — see
  VERIFICATION_STATUS).
- Multiple facilitators: coinbase, payai, cloudflare, eip-7702
- Smart facilitator router with auto-fallback
- Self-hosted facilitator (``x402.self_facilitator``): EIP-3009 verify +
  settlement broadcast on Pry infra — no external facilitator / Coinbase CDP.
  Opt-in via ``PRY_X402_SELF_FACILITATE=1`` (+ ``PRY_X402_FACILITATOR_KEY``,
  ``PRY_X402_FACILITATOR_RPC``).
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
import sys

# Reload-recomputable config: when this package is reloaded (tests patch
# secrets_backend.get_secret / env vars then call importlib.reload(x402)),
# re-execute _config so the secrets/env-backed constants are recomputed.
# On first import _config is not yet in sys.modules — the plain import below
# executes it exactly once.
if "pry.payments.x402._config" in sys.modules:
    importlib.reload(sys.modules["pry.payments.x402._config"])

from ._config import (
    EIP7702_RPC,
    EVM_TREASURY_SECRET,
    PAYMENT_VALIDITY_SECONDS,
    X402_DEBUG_MODE,
    X402_DEFAULT_ASSET,
    X402_DEFAULT_NETWORK,
    X402_DIR,
    X402_FACILITATOR_URL,
    X402_NETWORK_WALLETS,
    X402_OFFLINE_FORCE,
    X402_OFFLINE_MODE,
    X402_PLACEHOLDER_WALLETS,
    X402_SELF_FACILITATE,
    X402_SELF_FACILITATOR_KEY,
    X402_SELF_FACILITATOR_RPC,
    X402_TIMEOUT_SECONDS,
    X402_UNCONFIGURED_WALLET,
    X402_WALLET,
    logger,
    wallet_configured,
)
from .addresses import is_evm_address, is_solana_address, is_tron_address

from .helpers import _check_secret_permissions  # isort: skip
from .tokens import EIP7702_TOKEN_ADDRESSES  # isort: skip

# Re-export the full public surface. Submodules import their config from this
# package root (constants above), so these imports must come AFTER the config
# block to avoid circular initialization.
from .batch import (
    _batch_lock,
    _batch_payments,
    create_batch_payment,
    is_batch_paid,
    verify_batch_payment,
)
from .facilitator import (
    DEFAULT_FACILITATORS,
    ERC20_TRANSFER_SELECTOR,
    FacilitatorConfig,
    FacilitatorRouter,
    _facilitator_router,
    get_facilitator_router,
    register_facilitator,
    set_facilitator_router,
)
from .handler import X402Handler
from .scheme import (
    _NATIVE_ASSETS,
    ASSET_DECIMALS,
    CAIP2_NETWORK_IDS,
    COINGECKO_ASSET_IDS,
    SUPPORTED_ASSETS,
    SUPPORTED_NETWORKS,
    VERIFICATION_STATUS,
    X402_ASSET_USD_PER_UNIT,
    X402_ATTEST_ALGORITHM,
    X402_ATTEST_DOMAIN,
    X402_ATTEST_KEY_ENV,
    X402_ATTEST_SECRET_ENV,
    X402_ATTEST_VERSION,
    X402_ORACLE_SOURCE,
    X402_ORACLE_TTL_SECONDS,
    X402_ORACLE_URL,
    X402_PRICING,
    AssetUsdQuote,
    X402Asset,
    X402Network,
    X402Scheme,
    _asset_on_network,
    _decode_payment_signature,
    _default_networks_for_asset,
    _encode_payment_required_body,
    _legacy_payment_request,
    _to_atomic,
    asset_to_atomic,
    attest_payment_required,
    attestation_signer_address,
    attested_max_amount_required,
    build_multi_asset_accepts,
    build_payment_required,
    clear_price_cache,
    create_payment_request,
    flatten_supported_assets,
    get_asset_usd_price,
    is_asset_supported,
    network_family,
    network_verification_status,
    normalize_network_id,
    oracle_source_label,
    probe_oracle,
    require_payment_legacy,
    resolve_asset_entry,
    resolve_pay_to,
    resolve_price_usd,
    usd_per_unit_for,
    validate_client_amount,
    verify_payment_required_attestation,
)
from .self_facilitator import (
    CHAIN_ID_BY_NETWORK,
    NonceStore,
    SelfFacilitator,
    SettleErrorCode,
    SettleOutcome,
    VerifyResult,
)
from .solana_verifier import (
    DEFAULT_SOLANA_RPC_URL,
    SOLANA_RPC_TIMEOUT_SECONDS,
    SOLANA_USDC_MINT,
    verify_solana_payment,
)

# Single source of truth for Base USDT: SUPPORTED_ASSETS (x402/scheme.py) is
# authoritative. The V1 EIP7702_TOKEN_ADDRESSES entry previously hardcoded
# 0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb — that contract is DAI on Base,
# not USDT (verified via eth_call name()/symbol()). Derive it so the tables
# can never disagree again.
EIP7702_TOKEN_ADDRESSES["base"]["USDT"] = SUPPORTED_ASSETS["eip155:8453"]["USDT"]["contract"]

_check_secret_permissions()

__all__ = [
    "ASSET_DECIMALS",
    "CAIP2_NETWORK_IDS",
    "CHAIN_ID_BY_NETWORK",
    "COINGECKO_ASSET_IDS",
    "DEFAULT_FACILITATORS",
    "DEFAULT_SOLANA_RPC_URL",
    "EIP7702_RPC",
    "EIP7702_TOKEN_ADDRESSES",
    "ERC20_TRANSFER_SELECTOR",
    "EVM_TREASURY_SECRET",
    "PAYMENT_VALIDITY_SECONDS",
    "SOLANA_RPC_TIMEOUT_SECONDS",
    "SOLANA_USDC_MINT",
    "SUPPORTED_ASSETS",
    "SUPPORTED_NETWORKS",
    "VERIFICATION_STATUS",
    "X402_ASSET_USD_PER_UNIT",
    "X402_ATTEST_ALGORITHM",
    "X402_ATTEST_DOMAIN",
    "X402_ATTEST_KEY_ENV",
    "X402_ATTEST_SECRET_ENV",
    "X402_ATTEST_VERSION",
    "X402_DEBUG_MODE",
    "X402_DEFAULT_ASSET",
    "X402_DEFAULT_NETWORK",
    "X402_DIR",
    "X402_FACILITATOR_URL",
    "X402_NETWORK_WALLETS",
    "X402_OFFLINE_FORCE",
    "X402_OFFLINE_MODE",
    "X402_ORACLE_SOURCE",
    "X402_ORACLE_TTL_SECONDS",
    "X402_ORACLE_URL",
    "X402_PLACEHOLDER_WALLETS",
    "X402_PRICING",
    "X402_SELF_FACILITATE",
    "X402_SELF_FACILITATOR_KEY",
    "X402_SELF_FACILITATOR_RPC",
    "X402_TIMEOUT_SECONDS",
    "X402_UNCONFIGURED_WALLET",
    "X402_WALLET",
    "_NATIVE_ASSETS",
    "AssetUsdQuote",
    "FacilitatorConfig",
    "FacilitatorRouter",
    "NonceStore",
    "SelfFacilitator",
    "SettleErrorCode",
    "SettleOutcome",
    "VerifyResult",
    "X402Asset",
    "X402Handler",
    "X402Network",
    "X402Scheme",
    "_asset_on_network",
    "_batch_lock",
    "_batch_payments",
    "_decode_payment_signature",
    "_default_networks_for_asset",
    "_encode_payment_required_body",
    "_facilitator_router",
    "_legacy_payment_request",
    "_to_atomic",
    "asset_to_atomic",
    "attest_payment_required",
    "attestation_signer_address",
    "attested_max_amount_required",
    "build_multi_asset_accepts",
    "build_payment_required",
    "clear_price_cache",
    "create_batch_payment",
    "create_payment_request",
    "flatten_supported_assets",
    "get_asset_usd_price",
    "get_facilitator_router",
    "is_asset_supported",
    "is_batch_paid",
    "is_evm_address",
    "is_solana_address",
    "is_tron_address",
    "logger",
    "network_family",
    "network_verification_status",
    "normalize_network_id",
    "oracle_source_label",
    "probe_oracle",
    "register_facilitator",
    "require_payment_legacy",
    "resolve_asset_entry",
    "resolve_pay_to",
    "resolve_price_usd",
    "set_facilitator_router",
    "usd_per_unit_for",
    "validate_client_amount",
    "verify_batch_payment",
    "verify_payment_required_attestation",
    "verify_solana_payment",
    "wallet_configured",
]
