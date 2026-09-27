"""Address format validation for Pry's receive wallets.

Split out of ``wallet_setup`` so the rule that matters most is readable on its
own: an address we could not verify is REJECTED, never accepted with a shrug.
This is a receiving ``payTo`` — the address real money arrives at — so
"validation failed, assume it is fine" is the one failure mode that must not
exist. ``ImportError`` of eth_utils is different: that is a missing optional
accelerator, and the format check that already ran is a documented fallback.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

# ── Address validation ──────────────────────────────────────────────────────
_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
# base58 alphabet (Bitcoin-style, excludes 0/O/I/l)
_BASE58_ALPHABET = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
_TRON_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


def _redact(addr: str) -> str:
    """Log-safe address form: never the whole value."""
    a = addr.strip()
    return f"{a[:6]}…{a[-4:]}" if len(a) > 12 else "…"


def _is_evm_address(addr: str) -> bool:
    """True when ``addr`` is a 0x-prefixed 40-hex EVM address (42 chars)."""
    addr = addr.strip()
    if not _EVM_RE.fullmatch(addr):
        return False
    # eth_utils absent -> format-only (documented fallback). A failure INSIDE
    # validation -> reject: this is a receiving payTo, so an address we could
    # not verify must not be accepted.
    try:
        from eth_utils import (  # type: ignore[attr-defined]
            is_checksum_address,
            is_hex_address,
        )
    except ImportError:
        logger.debug("eth_utils absent; EVM wallet accepted on format: %s", _redact(addr))
        return True
    try:
        if not is_hex_address(addr):
            return False
        # Accept both checksummed and all-lowercase/all-uppercase addresses
        # (all-lowercase is a valid, non-checksummed representation).
        if addr == addr.lower() or addr == addr.upper():
            return True
        return is_checksum_address(addr)
    except (ValueError, TypeError):
        logger.debug("EVM wallet checksum validation failed; rejecting %s", _redact(addr))
        return False


def _is_solana_address(addr: str) -> bool:
    """True when ``addr`` is a 32-44 char base58 Solana address."""
    addr = addr.strip()
    if not (32 <= len(addr) <= 44):
        return False
    return all(c in _BASE58_ALPHABET for c in addr)


def _is_tron_address(addr: str) -> bool:
    """True when ``addr`` is a 34-char T-prefixed TRON base58 address."""
    return bool(addr and _TRON_RE.fullmatch(addr.strip()))


_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "evm": _is_evm_address,
    "solana": _is_solana_address,
    "tron": _is_tron_address,
}


def validate_address(family: str, addr: str) -> bool:
    """Validate ``addr`` against the address format for ``family``."""
    validator = _VALIDATORS.get(family)
    if validator is None:
        return False
    return validator(addr)
