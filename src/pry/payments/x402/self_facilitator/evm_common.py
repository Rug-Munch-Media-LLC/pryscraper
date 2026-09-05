"""Pry — shared seams for the EVM self-facilitator modules."""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

# Fixed gas limit fallback for ERC-20 settlement if eth_estimateGas is
# unavailable (USDC transferWithAuthorization costs ~65k; 100k is safe).
_DEFAULT_TX_GAS = 100_000


def _pkg() -> Any:
    """The self_facilitator package module, resolved lazily at call time.

    Wallet config and the scheme seams (``X402_WALLET``,
    ``X402_PLACEHOLDER_WALLETS``, ``resolve_asset_entry``,
    ``get_asset_usd_price``) are read through the package so tests that patch
    ``pry.payments.x402.self_facilitator.<name>`` keep working after the
    module→package split.
    """
    import pry.payments.x402.self_facilitator as pkg

    return pkg
