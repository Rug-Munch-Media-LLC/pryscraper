"""Pry — Solana x402 verifier constants (mints, program ids, RPC defaults).

SINGLE SOURCE OF TRUTH: the SUPPORTED_ASSETS table (x402/scheme.py) is
authoritative for which mints Pry accepts on solana:mainnet. The constants
below are DERIVED from that table so the verifier can never drift from what
is advertised. The hardcoded fallbacks match the canonical table and only
exist so this module stays importable (and the verifier fails closed, not
with an ImportError) if the package table is unavailable.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

try:
    from pry.payments.x402.scheme import SUPPORTED_ASSETS as _SUPPORTED_ASSETS

    _SOLANA_TABLE = _SUPPORTED_ASSETS["solana:mainnet"]
    SOLANA_USDC_MINT = str(_SOLANA_TABLE["USDC"]["contract"])
    SOLANA_USDT_MINT = str(_SOLANA_TABLE["USDT"]["contract"])
    SOLANA_NATIVE_DECIMALS = int(_SOLANA_TABLE["SOL"]["decimals"])
except (ImportError, KeyError, TypeError, ValueError):  # pragma: no cover
    # Defensive fallback — must mirror scheme.py's solana:mainnet entries.
    SOLANA_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    SOLANA_USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    SOLANA_NATIVE_DECIMALS = 9

# Advertised asset symbols for solana:mainnet (mirrors SUPPORTED_ASSETS keys).
SOLANA_NATIVE_ASSET = "SOL"
SUPPORTED_SOLANA_ASSETS: tuple[str, ...] = ("USDC", "USDT", SOLANA_NATIVE_ASSET)

# SPL mint -> asset symbol for every verifiable SPL asset on solana:mainnet.
SUPPORTED_SOLANA_MINTS: dict[str, str] = {
    SOLANA_USDC_MINT: "USDC",
    SOLANA_USDT_MINT: "USDT",
}

# Default public Solana mainnet RPC (override per call / env in production).
DEFAULT_SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# RPC timeout — verify is a single round-trip, keep it short.
SOLANA_RPC_TIMEOUT_SECONDS = 15.0

# SPL Token program id — sanity-check the parsed instruction came from the
# canonical token program (not a custom program with a spoofed "parsed").
# Well-known public constant, NOT a secret: noqa S105 (bandit heuristically
# treats base58 ids beginning with "Token" as credentials).
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"  # noqa: S105

# Solana System program id — native SOL (lamports) transfers.
# Well-known public constant, NOT a secret.
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"

# Only transferChecked carries the mint in jsonParsed output; plain SPL
# ``transfer`` does not, so it cannot be attributed to a specific mint
# without extra account-resolution RPC calls. Verifiable SPL instruction
# types:
VERIFIABLE_TYPES = ("transferChecked",)

# Parsed system-program instruction types that move lamports as a payment.
# Only the plain ``transfer`` counts — createAccount/closeAccount/advanceNonce
# also move lamports but are account-management operations, not payments.
NATIVE_TRANSFER_TYPES = ("transfer",)
