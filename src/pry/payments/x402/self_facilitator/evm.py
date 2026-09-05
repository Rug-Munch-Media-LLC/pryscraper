"""Pry — the ``SelfFacilitator``: local EVM EIP-3009 verify + settle.

Thin facade: the implementation lives in focused sibling modules
(``evm_verify``, ``evm_settle``, ``evm_rpc``, ``evm_trackers``,
``evm_common``); this module composes them into :class:`SelfFacilitator`
and re-exports the historical module surface.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from eth_account import Account
from eth_keys.datatypes import PrivateKey

from pry.payments.x402 import (
    X402_SELF_FACILITATOR_KEY,
    X402_SELF_FACILITATOR_RPC,
    X402_TIMEOUT_SECONDS,
)

from .evm_common import _DEFAULT_TX_GAS, _pkg
from .evm_rpc import EVMRpcMixin
from .evm_settle import EVMSettleMixin
from .evm_trackers import EVMTrackerMixin
from .evm_verify import EVMVerifyMixin
from .nonces import NonceStore

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

__all__ = ["_DEFAULT_TX_GAS", "SelfFacilitator", "_pkg"]


class SelfFacilitator(
    EVMVerifyMixin,
    EVMSettleMixin,
    EVMRpcMixin,
    EVMTrackerMixin,
):
    """Self-hosted x402 facilitator (EVM ``exact`` scheme).

    Args:
        pay_to: Receiving wallet. Must equal the authorization's ``to``.
            Defaults to ``X402_WALLET``; verification fails closed while the
            wallet is the ``X402_UNCONFIGURED_WALLET`` placeholder.
        facilitator_key: EVM private key used to pay gas when broadcasting
            settlement. Optional for verify; required for settle.
        rpc_url: JSON-RPC endpoint for settlement broadcast (optional; verify
            is fully local).
        domain_name / domain_version: EIP-712 domain of the EIP-3009 token
            (defaults to Circle USDC "USD Coin" / "2").
        nonce_path: JSON file backing the nonce store (defaults to
            ``X402_DIR/self_facilitator_nonces.json``).
        max_nonces: Bound of the in-memory replay set.
        transport: Optional httpx transport (tests).
        max_settled: Bound of the idempotent settled-tx tracker.
        max_pending: Bound of the in-flight pending-settlement tracker.
    """

    def __init__(
        self,
        *,
        pay_to: str = "",
        facilitator_key: str = "",
        rpc_url: str = "",
        domain_name: str = "",
        domain_version: str = "",
        nonce_path: Path | str | None = None,
        max_nonces: int = 10_000,
        timeout_seconds: float = X402_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        max_settled: int = 10_000,
        max_pending: int = 10_000,
    ) -> None:
        self.pay_to = self._normalize_address(pay_to or _pkg().X402_WALLET)
        self.facilitator_key = facilitator_key or X402_SELF_FACILITATOR_KEY
        self.rpc_url = rpc_url or X402_SELF_FACILITATOR_RPC
        self.domain_name = domain_name or os.getenv("PRY_X402_EIP712_NAME", "USD Coin")
        self.domain_version = domain_version or os.getenv("PRY_X402_EIP712_VERSION", "2")
        self.timeout_seconds = timeout_seconds
        self.nonces = NonceStore(
            path=nonce_path or _pkg().X402_DIR / "self_facilitator_nonces.json",
            max_size=max_nonces,
        )
        self._transport = transport
        key_hex = self.facilitator_key.removeprefix("0x") if self.facilitator_key else ""
        self._signer: PrivateKey | None = (
            PrivateKey(bytes.fromhex(key_hex)) if len(key_hex) == 64 else None
        )
        self._acct: Any = Account.from_key(bytes.fromhex(key_hex)) if self._signer else None
        # Settlement hardening: bounded idempotency + in-flight trackers.
        self._settled_txs: OrderedDict[str, Any] = OrderedDict()
        self._max_settled = max(int(max_settled), 1)
        self._pending_settlements: OrderedDict[str, Any] = OrderedDict()
        self._max_pending = max(int(max_pending), 1)
