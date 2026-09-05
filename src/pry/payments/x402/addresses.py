"""x402 address-format validation.

Family-specific address shapes used by the payTo resolver so an EVM hex
address can NEVER occupy a Solana/TRON slot (and vice-versa). Formats:
  EVM    — 0x + 40 hex chars (42 total)
  Solana — base58, 44 chars (ed25519 pubkey)
  TRON   — base58check, 34 chars, starts with 'T'
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re

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
