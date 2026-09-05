"""Pry — Solana multi-asset x402 payment verifier (facade).

Thin re-export facade over the split Solana verifier modules:

  - ``solana_constants`` — mints, program ids, RPC defaults
  - ``solana_parse``     — jsonParsed instruction/amount parsing helpers
  - ``solana_result``    — stable ``{"verified": ...}`` result builders
  - ``solana_transfer``  — ``verify_solana_payment`` (RPC + verification)

All previously-public and test-accessed symbols are re-exported here so
``from pry.payments.x402.solana_verifier import X`` keeps working unchanged.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry.payments.x402.solana_constants import (
    DEFAULT_SOLANA_RPC_URL,
    NATIVE_TRANSFER_TYPES,
    SOLANA_NATIVE_ASSET,
    SOLANA_NATIVE_DECIMALS,
    SOLANA_RPC_TIMEOUT_SECONDS,
    SOLANA_USDC_MINT,
    SOLANA_USDT_MINT,
    SPL_TOKEN_PROGRAM_ID,
    SUPPORTED_SOLANA_ASSETS,
    SUPPORTED_SOLANA_MINTS,
    SYSTEM_PROGRAM_ID,
    VERIFIABLE_TYPES,
)
from pry.payments.x402.solana_parse import (  # noqa: F401
    _amount_usd_value,
    _confirmed_at,
    _iter_spl_instructions,
    _iter_system_transfers,
    _parse_amount,
    _parse_lamports,
)
from pry.payments.x402.solana_result import (  # noqa: F401
    _failure,
    _success,
)
from pry.payments.x402.solana_transfer import (
    verify_solana_payment,
)

__all__ = [
    "DEFAULT_SOLANA_RPC_URL",
    "NATIVE_TRANSFER_TYPES",
    "SOLANA_NATIVE_ASSET",
    "SOLANA_NATIVE_DECIMALS",
    "SOLANA_RPC_TIMEOUT_SECONDS",
    "SOLANA_USDC_MINT",
    "SOLANA_USDT_MINT",
    "SPL_TOKEN_PROGRAM_ID",
    "SUPPORTED_SOLANA_ASSETS",
    "SUPPORTED_SOLANA_MINTS",
    "SYSTEM_PROGRAM_ID",
    "VERIFIABLE_TYPES",
    "verify_solana_payment",
]
