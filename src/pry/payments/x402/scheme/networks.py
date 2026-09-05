"""Pry — x402 network/asset compatibility and payTo resolution.

The canonical multi-chain / multi-asset acceptance table lives here:
``SUPPORTED_ASSETS`` is the single source of truth for which (network, asset)
pairs Pry accepts for x402 payments, keyed by CAIP-2 network id + asset
symbol. `verification` names the authorization method:

    eip3009 — ERC-20 transferWithAuthorization (USDC)
    permit2 — ERC-20 Permit2 (USDT / ARB / WETH / …)
    native  — plain value transfer of the chain's native asset
    spl     — Solana SPL token transfer
    trc20   — TRON TRC-20 transfer

`kind` distinguishes contract tokens from native assets (contract == ""
for native). Contract addresses are well-known mainnet addresses.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os
from typing import Any

from pry.payments.x402 import (
    is_evm_address,
    is_solana_address,
    is_tron_address,
)

from .enums import X402Asset, X402Network
from .networks_evm import EVM_ASSETS
from .networks_solana import SOLANA_ASSETS
from .networks_tron import TRON_ASSETS


def _scheme_pkg() -> Any:
    """The scheme package module, resolved lazily at call time.

    Wallet config (``X402_WALLET``, ``X402_NETWORK_WALLETS``,
    ``X402_PLACEHOLDER_WALLETS``) is read through the package so tests that
    patch ``pry.payments.x402.scheme.X402_WALLET`` (and friends) keep working
    after the module→package split.
    """
    import pry.payments.x402.scheme as pkg

    return pkg


# CAIP-2 network ids. Legacy x402 network names (X402Network enum values) map
# to these; both spellings are accepted everywhere.
CAIP2_NETWORK_IDS: dict[str, str] = {
    "base": "eip155:8453",
    "ethereum": "eip155:1",
    "arbitrum": "eip155:42161",
    "optimism": "eip155:10",
    "polygon": "eip155:137",
    "solana": "solana:mainnet",
    "tron": "tron:mainnet",
}

SUPPORTED_NETWORKS: list[dict[str, Any]] = [
    {"network": "eip155:8453", "name": "Base", "family": "evm", "chain": "eip155"},
    {"network": "eip155:1", "name": "Ethereum", "family": "evm", "chain": "eip155"},
    {"network": "eip155:42161", "name": "Arbitrum", "family": "evm", "chain": "eip155"},
    {"network": "eip155:10", "name": "Optimism", "family": "evm", "chain": "eip155"},
    {"network": "eip155:137", "name": "Polygon", "family": "evm", "chain": "eip155"},
    {"network": "solana:mainnet", "name": "Solana", "family": "solana", "chain": "solana"},
    {"network": "tron:mainnet", "name": "TRON", "family": "tron", "chain": "tron"},
]

SUPPORTED_ASSETS: dict[str, dict[str, dict[str, Any]]] = {
    **EVM_ASSETS,
    **SOLANA_ASSETS,
    **TRON_ASSETS,
}


# Verification status per chain family — what is REAL vs scaffolded.
# ``status`` is the machine-readable label exposed by the health + pricing
# endpoints: "live" (EVM — EIP-7702 self-verify + facilitators; Solana —
# SPL RPC verifier, getTransaction jsonParsed USDC transferChecked; TRON —
# TRC-20 Grid verifier, gettransactioninfobyid USDT Transfer event).
VERIFICATION_STATUS: dict[str, dict[str, Any]] = {
    "evm": {
        "status": "live",
        "real": True,
        "scaffolded": False,
        "note": "EIP-7702 self-verify (receipt + payTo/amount) and external facilitators",
    },
    "solana": {
        "status": "live",
        "real": True,
        "scaffolded": False,
        "note": "SPL RPC verifier — getTransaction jsonParsed USDC transferChecked to the configured Solana wallet",
    },
    "tron": {
        "status": "scaffolded:needs_facilitator",
        "real": False,
        "scaffolded": True,
        "note": "TRON scaffolded — no TRC-20 settlement verifier is wired/exposed yet; do not claim verified",
    },
}


def normalize_network_id(network: str) -> str:
    """Map a legacy x402 network name (or CAIP-2 id) to the CAIP-2 id.

    Unknown values pass through unchanged so callers can decide how to treat
    them; empty input stays empty.
    """
    if not network:
        return network
    return CAIP2_NETWORK_IDS.get(network.lower(), network)


def network_family(network: str) -> str:
    """Return the chain family for a network: evm | solana | tron | unknown."""
    network_id = normalize_network_id(network)
    if ":" not in network_id:
        return "unknown"
    prefix = network_id.split(":", 1)[0]
    if prefix == "eip155":
        return "evm"
    if prefix == "solana":
        return "solana"
    if prefix == "tron":
        return "tron"
    return "unknown"


def resolve_pay_to(
    network: str,
    wallets: dict[str, str] | None = None,
    evm_wallet: str | None = None,
) -> str:
    """Resolve the payTo (receiving) address for ``network`` — family-aware.

    EVM networks (eip155:*) use the per-network override from the wallet map
    (``PRY_X402_WALLET_BASE`` etc.) or, failing that, the shared EVM treasury
    ``evm_wallet`` (defaults to ``X402_WALLET``, itself gopass
    ``evm_treasury_address`` by default). Solana resolves to
    ``PRY_X402_WALLET_SOLANA`` and TRON to ``PRY_X402_WALLET_TRON``.

    There is NO cross-family fallback: a Solana/TRON invoice NEVER emits an
    EVM hex address and an EVM invoice never emits a base58 address. The
    resolved address is format-checked against its family
    (``is_evm_address`` / ``is_solana_address`` / ``is_tron_address``);
    unconfigured, placeholder, or shape-mismatched values return "" so
    callers fail closed instead of advertising a fake payTo.

    ``wallets``/``evm_wallet`` override the default wallet sources. Callers
    that expose module-level wallet attributes (e.g. packs.py) pass them
    explicitly so the resolution seam stays patchable in tests.
    """
    pkg = _scheme_pkg()
    network_wallets = pkg.X402_NETWORK_WALLETS if wallets is None else wallets
    evm = pkg.X402_WALLET if evm_wallet is None else evm_wallet
    family = network_family(network)
    if family == "solana":
        pay_to = network_wallets.get("solana:mainnet", "")
        if not is_solana_address(pay_to):
            return ""
    elif family == "tron":
        pay_to = network_wallets.get("tron:mainnet", "")
        if not is_tron_address(pay_to):
            return ""
    elif family == "evm":
        network_id = normalize_network_id(network)
        pay_to = network_wallets.get(network_id) or evm
        if not is_evm_address(pay_to):
            return ""
    else:
        return ""
    if pay_to in pkg.X402_PLACEHOLDER_WALLETS:
        return ""
    return pay_to


def treasury_wallets() -> dict[str, str]:
    """Return the configured per-chain treasury addresses for the pricing endpoint.

    Reads the operator env vars directly (``PRY_X402_WALLET`` for EVM,
    ``PRY_X402_WALLET_SOLANA``, ``PRY_X402_WALLET_TRON``) so the live
    ``/v1/x402/pricing`` response surfaces the ACTUAL configured treasuries
    instead of a stale/empty module-level snapshot. Each address is
    format-validated through :func:`resolve_pay_to` (family-aware, fail
    closed) so an unconfigured or malformed wallet is reported as ``""``
    rather than a fake payTo.
    """
    return {
        "evm": resolve_pay_to("base", wallets={}, evm_wallet=os.getenv("PRY_X402_WALLET", "")),
        "solana": resolve_pay_to(
            "solana:mainnet",
            wallets={"solana:mainnet": os.getenv("PRY_X402_WALLET_SOLANA", "")},
        ),
        "tron": resolve_pay_to(
            "tron:mainnet",
            wallets={"tron:mainnet": os.getenv("PRY_X402_WALLET_TRON", "")},
        ),
    }


def network_verification_status(network: str) -> str:
    """Return the verification-status label for a network.

    ``"live"`` for EVM chains (EIP-7702 self-verify + facilitators) and
    Solana (SPL RPC verifier — getTransaction jsonParsed USDC
    transferChecked); ``"scaffolded:needs_facilitator"`` for TRON
    (structure/price/asset validated; on-chain settlement NOT verified until
    a facilitator impl or TRC-20 verifier is registered); ``"unknown"``
    otherwise. Exposed by the health + pricing endpoints so operators never
    mistake a scaffold for real settlement verification.
    """
    status = VERIFICATION_STATUS.get(network_family(network), {})
    return str(status.get("status", "unknown"))


def resolve_asset_entry(network: str, asset: str) -> dict[str, Any] | None:
    """Look up the canonical SUPPORTED_ASSETS entry for (network, asset).

    Accepts legacy network names or CAIP-2 ids. Returns None when the pair is
    not in the acceptance table.
    """
    network_id = normalize_network_id(network)
    if not network_id or not asset:
        return None
    return SUPPORTED_ASSETS.get(network_id, {}).get(asset.upper())


def is_asset_supported(network: str, asset: str) -> bool:  # test-only
    """Return True when (network, asset) is in the canonical acceptance table."""
    return resolve_asset_entry(network, asset) is not None


def flatten_supported_assets() -> list[dict[str, Any]]:
    """Flatten SUPPORTED_ASSETS into a single list of asset entries."""
    flat: list[dict[str, Any]] = []
    for network_id, assets in SUPPORTED_ASSETS.items():
        for asset, entry in assets.items():
            flat.append(
                {
                    "asset": asset,
                    "network": network_id,
                    "name": entry.get("name", asset),
                    "contract": entry.get("contract", ""),
                    "decimals": entry.get("decimals", 6),
                    "verification": entry.get("verification", ""),
                    "kind": entry.get("kind", ""),
                }
            )
    return flat


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
        X402Asset.WETH.value: [
            X402Network.ETHEREUM.value,
            X402Network.BASE.value,
            X402Network.ARBITRUM.value,
            X402Network.OPTIMISM.value,
            X402Network.POLYGON.value,
        ],
        X402Asset.ARB.value: [X402Network.ARBITRUM.value],
        X402Asset.SOL.value: [X402Network.SOLANA.value],
        X402Asset.MATIC.value: [X402Network.POLYGON.value],
        X402Asset.POL.value: [X402Network.POLYGON.value],
        X402Asset.TRX.value: [X402Network.TRON.value],
        X402Asset.BTC.value: [X402Network.BITCOIN.value],
        X402Asset.LTC.value: [X402Network.LITECOIN.value],
        X402Asset.DOGE.value: [X402Network.DOGECOIN.value],
    }
    return mapping.get(asset, [X402Network.BASE.value])


def _asset_on_network(asset: str, network: str) -> bool:
    """Check whether an asset is generally supported on a network."""
    return network in _default_networks_for_asset(asset)
