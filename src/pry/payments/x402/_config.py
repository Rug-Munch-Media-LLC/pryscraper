"""x402 package configuration — env/secrets-backed constants.

Split out of the package ``__init__`` (god-file split). All values here are
recomputed by ``importlib.reload(pry.payments.x402)`` because the package
``__init__`` reloads this module before re-binding its names — tests patch
``secrets_backend.get_secret`` / env vars and reload the package to assert
the new values.

Do NOT import ``pry.payments.x402.scheme`` (or any sibling submodule) from
here: submodules import their config from the package root, which imports
this module first — that would be circular initialization.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os

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
# Reload-recomputable: the package __init__ reloads this module so
# importlib.reload(x402) recomputes the secrets-backed values — tests patch
# secrets_backend.get_secret and reload the package to assert the new values.
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

# Sentinel payTo address used until an operator configures a real wallet.
# Verification fails closed while this placeholder is in effect. Backported
# from x402-coffer (same value) so the two vendored copies share one sentinel.
X402_UNCONFIGURED_WALLET: str = "coffer-unconfigured-wallet"

# Wallets that are NEVER a real receiving address. The self-facilitator and the
# accept builders treat these as "not configured" and fail closed rather than
# silently emitting a fake payTo.
#
# NOTE (2026-08-30): "0x1E3AC01d0fdb976179790BDD02823196A92705C9" is the REAL
# operator-confirmed EVM treasury (all eip155 chains). It was previously
# mistaken for coffer's CONFIGURED_WALLET sentinel and listed here as a
# placeholder — it is NOT. Do not re-add it. Placeholder entries are only the
# genuine sentinels below (empty string + dev/test markers).
#
# ``X402_UNCONFIGURED_WALLET`` is the canonical sentinel; the legacy
# ``"pry-default-wallet"`` / ``"pry-default"`` strings are kept as
# backward-compatible dev/test markers so pre-existing configs still fail
# closed.
X402_PLACEHOLDER_WALLETS: frozenset[str] = frozenset(
    {
        "",
        X402_UNCONFIGURED_WALLET,
        "pry-default-wallet",
        "pry-default",
        "0xRMI_PLATFORM_WALLET",
    }
)


def wallet_configured(wallet: str) -> bool:
    """True only when ``wallet`` is a real, non-placeholder receiving address."""
    return bool(wallet and wallet not in X402_PLACEHOLDER_WALLETS)


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

# Production guard (quality audit #4): PRY_DATABASE_URL is the production
# indicator (dev defaults to embedded SQLite — see pry.core.db.session). If
# offline mode is somehow active while a database is configured, auto-disable
# it — a stale DEBUG=true in prod must never auto-verify all payments.
# Escape hatch: PRY_X402_OFFLINE_FORCE=true keeps offline mode on (for
# testing against a configured DB) but still logs a warning.
X402_OFFLINE_FORCE: bool = _env_flag("PRY_X402_OFFLINE_FORCE")
if X402_OFFLINE_MODE and bool(os.getenv("PRY_DATABASE_URL")):
    if X402_OFFLINE_FORCE:
        logger.warning(
            "X402_OFFLINE_MODE forced ON in production (PRY_DATABASE_URL is set) "
            "via PRY_X402_OFFLINE_FORCE=true — ALL payment verification is BYPASSED."
        )
    else:
        X402_OFFLINE_MODE = False
        logger.critical("X402_OFFLINE_MODE auto-disabled in production (PRY_DATABASE_URL is set)")
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
