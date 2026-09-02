"""Pry — x402 (HTTP 402 Payment Required) protocol implementation.

Implements the x402 v1 spec from https://github.com/coinbase/x402

This package was split out of the original ``x402.py`` god module. The
secrets/env-backed configuration lives here (package root) so that
``importlib.reload(x402)`` recomputes constants such as ``X402_WALLET``
when tests patch ``secrets_backend.get_secret``. Domain code lives in:

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

import logging
import os
import re

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

X402_DIR = PRY_DATA_DIR / "x402"
X402_DIR.mkdir(parents=True, exist_ok=True)


def _env_flag(name: str) -> bool:
    """Parse a common truthy env-var flag."""
    return os.getenv(name, "false").lower() in ("1", "true", "yes")


# Prefer gopass for the x402 wallet and facilitator URL. Env vars override only
# if the backend returns an empty string. This lets you:
#   gopass insert -m pry/x402_wallet               # persistent across restarts
#   PRY_X402_WALLET=0x...                          # one-off override (CI, dev)
#
# Kept at the package root (not in a submodule) so importlib.reload(x402)
# recomputes the secrets-backed values — tests patch secrets_backend.get_secret
# and reload the package to assert the new values.
# The shared EVM treasury receiving address is sourced from gopass under the
# secret name `evm_treasury_address` (see .env.example). Reference the NAME
# only — never hardcode a wallet value into source. Every EVM network shares
# this treasury; Solana/TRON use DISTINCT base58 addresses and must be
# configured separately (PRY_X402_WALLET_SOLANA / PRY_X402_WALLET_TRON).
# This is a secret NAME, never a value.
EVM_TREASURY_SECRET = "evm_treasury_address"  # noqa: S105

try:
    from pry.core.secrets_backend import get_secret as _gs

    # Receive-wallet precedence: an explicit x402 wallet first (gopass
    # `x402_wallet` / PRY_X402_WALLET), then the shared EVM treasury (gopass
    # `evm_treasury_address` / PRY_EVM_TREASURY_ADDRESS). Never hardcoded;
    # unresolved stays "" and is treated as unconfigured (fail closed — the
    # accept builders never emit a placeholder payTo).
    X402_WALLET: str = (
        _gs("x402_wallet") or _gs(EVM_TREASURY_SECRET) or os.getenv("PRY_X402_WALLET", "")
    )
    X402_FACILITATOR_URL: str = _gs("x402_facilitator") or os.getenv(
        "PRY_X402_FACILITATOR", "https://x402.org/facilitator"
    )
except ImportError:
    X402_WALLET = os.getenv("PRY_X402_WALLET", "") or os.getenv("PRY_EVM_TREASURY_ADDRESS", "")
    X402_FACILITATOR_URL = os.getenv("PRY_X402_FACILITATOR", "https://x402.org/facilitator")

# Wallets that are NEVER a real receiving address. The self-facilitator and the
# accept builders treat these as "not configured" and fail closed rather than
# silently emitting a fake payTo. Kept at the package root so
# importlib.reload(x402) recomputes nothing but the sentinel is stable.
#
# NOTE (2026-08-30): "0x1E3AC01d0fdb976179790BDD02823196A92705C9" is the REAL
# operator-confirmed EVM treasury (all eip155 chains). It was previously
# mistaken for coffer's CONFIGURED_WALLET sentinel and listed here as a
# placeholder — it is NOT. Do not re-add it. Placeholder entries are only the
# genuine sentinels below (empty string + dev/test markers).
X402_PLACEHOLDER_WALLETS: frozenset[str] = frozenset(
    {
        "",
        "pry-default-wallet",
        "pry-default",
        "0xRMI_PLATFORM_WALLET",
    }
)


def wallet_configured(wallet: str) -> bool:
    """True only when ``wallet`` is a real, non-placeholder receiving address."""
    return bool(wallet and wallet not in X402_PLACEHOLDER_WALLETS)


# ── Address-format validation ──────────────────────────────────────────────
# Family-specific address shapes used by the payTo resolver so an EVM hex
# address can NEVER occupy a Solana/TRON slot (and vice-versa). Formats:
#   EVM    — 0x + 40 hex chars (42 total)
#   Solana — base58, 44 chars (ed25519 pubkey)
#   TRON   — base58check, 34 chars, starts with 'T'
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{44}$")
_TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


def is_evm_address(addr: str) -> bool:
    """True when ``addr`` is a 0x-prefixed 40-hex EVM address (42 chars)."""
    return bool(addr and _EVM_ADDRESS_RE.fullmatch(addr.strip()))


def is_solana_address(addr: str) -> bool:
    """True when ``addr`` is a 44-char base58 Solana address."""
    return bool(addr and _SOLANA_ADDRESS_RE.fullmatch(addr.strip()))


def is_tron_address(addr: str) -> bool:
    """True when ``addr`` is a 34-char T-prefixed TRON base58 address."""
    return bool(addr and _TRON_ADDRESS_RE.fullmatch(addr.strip()))


# NOTE: literal defaults are equal to X402Network.BASE.value and
# X402Asset.USDC.value; the enums live in x402.scheme which is imported after
# this config block so the constants stay reload-recomputable.
X402_DEFAULT_NETWORK: str = os.getenv("PRY_X402_NETWORK", "base")
X402_DEFAULT_ASSET: str = os.getenv("PRY_X402_ASSET", "USDC")

# Per-network receiving wallets (CAIP-2 keyed). A Solana/TRON receiving
# address is NOT the same as the EVM wallet, so operators MUST configure
# these before accepting real payments on those chains. EVM networks share
# the resolved treasury (X402_WALLET — itself gopass `evm_treasury_address`
# by default); solana/tron stay "" (fail closed) until explicitly configured.
X402_NETWORK_WALLETS: dict[str, str] = {
    "eip155:8453": os.getenv("PRY_X402_WALLET_BASE", X402_WALLET),
    "eip155:1": os.getenv("PRY_X402_WALLET_ETHEREUM", X402_WALLET),
    "eip155:42161": os.getenv("PRY_X402_WALLET_ARBITRUM", X402_WALLET),
    "eip155:10": os.getenv("PRY_X402_WALLET_OPTIMISM", X402_WALLET),
    "eip155:137": os.getenv("PRY_X402_WALLET_POLYGON", X402_WALLET),
    "eip155:56": os.getenv("PRY_X402_WALLET_BNB", X402_WALLET),
    "eip155:43114": os.getenv("PRY_X402_WALLET_AVALANCHE", X402_WALLET),
    "solana:mainnet": os.getenv("PRY_X402_WALLET_SOLANA", ""),
    "tron:mainnet": os.getenv("PRY_X402_WALLET_TRON", ""),
}

# Offline mode is a DEV-ONLY bypass: it makes every verify/settle succeed
# without touching a facilitator. It must NEVER be active in production, so
# it requires BOTH PRY_X402_OFFLINE=true AND DEBUG=true (or PRY_DEBUG=true).
# Without the debug gate a bare PRY_X402_OFFLINE=true is ignored loudly.
X402_DEBUG_MODE: bool = _env_flag("DEBUG") or _env_flag("PRY_DEBUG")
X402_OFFLINE_MODE: bool = _env_flag("PRY_X402_OFFLINE") and X402_DEBUG_MODE
if _env_flag("PRY_X402_OFFLINE") and not X402_DEBUG_MODE:
    logger.warning(
        "PRY_X402_OFFLINE=true IGNORED: offline mode requires DEBUG=true (or PRY_DEBUG=true) "
        "and is intended for local development only."
    )
if X402_OFFLINE_MODE:
    logger.warning(
        "x402_offline_mode_active: ALL payment verification is BYPASSED — "
        "dev-only setting. DO NOT run with PRY_X402_OFFLINE=true in production."
    )
X402_TIMEOUT_SECONDS: float = float(os.getenv("PRY_X402_TIMEOUT", "15"))

# How long a verified payment_id stays valid for replay (access reuse).
# After this window the client must pay again. Payments recorded before this
# setting existed (no expires_at) are treated as expired (fail closed).
PAYMENT_VALIDITY_SECONDS: int = int(os.getenv("PRY_X402_PAYMENT_TTL", "3600"))

# EIP-7702 self-verify RPC endpoints (public defaults, override via env)
EIP7702_RPC: dict[str, str] = {
    "base": os.getenv("PRY_X402_BASE_RPC", "https://mainnet.base.org"),
    "ethereum": os.getenv("PRY_X402_ETH_RPC", "https://eth.llamarpc.com"),
    "polygon": os.getenv("PRY_X402_POLYGON_RPC", "https://polygon.drpc.org"),
    "arbitrum": os.getenv("PRY_X402_ARBITRUM_RPC", "https://arb1.arbitrum.io/rpc"),
    "optimism": os.getenv("PRY_X402_OPTIMISM_RPC", "https://mainnet.optimism.io"),
    "bnb": os.getenv("PRY_X402_BNB_RPC", "https://bsc-dataseed.binance.org"),
    "avalanche": os.getenv("PRY_X402_AVALANCHE_RPC", "https://api.avax.network/ext/bc/C/rpc"),
    "base-sepolia": os.getenv("PRY_X402_BASE_SEPOLIA_RPC", "https://sepolia.base.org"),
}

# Canonical ERC-20 token addresses used to validate EIP-7702 self-verify txs.
# A successful receipt alone is NOT proof of payment — the tx must have been
# sent TO one of these token contracts with a transfer() to our wallet for at
# least the server-side price. Addresses are well-known mainnet addresses.
#
# NOTE — Base USDT single source: the Base USDT entry is derived below from
# SUPPORTED_ASSETS (x402/scheme.py) so the two tables can never disagree.
# The V1 table previously hardcoded 0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb
# for Base USDT — an error: that contract is DAI on Base ("Dai Stablecoin",
# 18 decimals, confirmed via eth_call), not USDT. The authoritative address is
# the official bridged Tether USD 0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2.
EIP7702_TOKEN_ADDRESSES: dict[str, dict[str, str]] = {
    "base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        # USDT derived from SUPPORTED_ASSETS below (single source of truth).
    },
    "ethereum": {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    },
    "polygon": {
        "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
    },
    "arbitrum": {
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
    },
    "optimism": {
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097F85F",
        "USDT": "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58",
    },
    "bnb": {
        "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        "USDT": "0x55d398326f99059fF775485246999027B3197955",
    },
    "avalanche": {
        "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
        "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7",
    },
    "base-sepolia": {
        "USDC": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    },
}

# Self-hosted x402 facilitator (no external facilitator / Coinbase CDP).
# Opt-in: PRY_X402_SELF_FACILITATE=1 switches the FacilitatorRouter to the
# local SelfFacilitator. PRY_X402_FACILITATOR_KEY is the EVM private key used
# to pay gas when broadcasting settlement; PRY_X402_FACILITATOR_RPC is the
# JSON-RPC endpoint. See x402/self_facilitator.py.
X402_SELF_FACILITATE: bool = _env_flag("PRY_X402_SELF_FACILITATE")
X402_SELF_FACILITATOR_KEY: str = os.getenv("PRY_X402_FACILITATOR_KEY", "")
X402_SELF_FACILITATOR_RPC: str = os.getenv("PRY_X402_FACILITATOR_RPC", "")
if X402_SELF_FACILITATE and not (X402_SELF_FACILITATOR_KEY and X402_SELF_FACILITATOR_RPC):
    logger.warning(
        "PRY_X402_SELF_FACILITATE=1 but PRY_X402_FACILITATOR_KEY and/or "
        "PRY_X402_FACILITATOR_RPC are missing: verify works, settle will be unavailable."
    )

# Re-export the full public surface. Submodules import their config from this
# package root (constants above), so these imports must come AFTER the config
# block to avoid circular initialization.
from .batch import (  # noqa: E402
    _batch_lock,
    _batch_payments,
    create_batch_payment,
    is_batch_paid,
    verify_batch_payment,
)
from .facilitator import (  # noqa: E402
    DEFAULT_FACILITATORS,
    ERC20_TRANSFER_SELECTOR,
    FacilitatorConfig,
    FacilitatorRouter,
    _facilitator_router,
    get_facilitator_router,
    register_facilitator,
    set_facilitator_router,
)
from .handler import X402Handler  # noqa: E402
from .scheme import (  # noqa: E402
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
    _encode_payment_response,
    _from_atomic,
    _legacy_payment_request,
    _to_atomic,
    asset_to_atomic,
    attest_payment_required,
    attestation_signer_address,
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
from .self_facilitator import (  # noqa: E402
    CHAIN_ID_BY_NETWORK,
    NonceStore,
    SelfFacilitator,
    SettleErrorCode,
    SettleOutcome,
    VerifyResult,
)
from .solana_verifier import (  # noqa: E402
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
    "_encode_payment_response",
    "_facilitator_router",
    "_from_atomic",
    "_legacy_payment_request",
    "_to_atomic",
    "asset_to_atomic",
    "attest_payment_required",
    "attestation_signer_address",
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
