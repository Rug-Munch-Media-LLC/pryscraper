"""Pry — settlement trackers for the EVM self-facilitator.

Idempotency key derivation and the bounded pending/settled trackers that
back ``settle_with_details``.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from eth_utils import to_checksum_address  # type: ignore[attr-defined]

from pry.payments.x402 import X402_DEFAULT_ASSET
from pry.payments.x402.scheme import normalize_network_id

from .crypto import _nonce_hex
from .evm_common import _pkg
from .networks import _chain_id_for

if TYPE_CHECKING:
    from collections import OrderedDict


class EVMTrackerMixin:
    """Settlement idempotency + in-flight tracking for :class:`SelfFacilitator`."""

    # ── settlement trackers ──────────────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        """Number of settlement attempts currently in-flight (pending)."""
        return sum(1 for s in self._pending_settlements.values() if s.get("status") == "pending")

    def _settlement_id(self, payment: dict[str, Any]) -> str:
        """Idempotency key for a payment: payment_id, else EIP-3009 nonce key."""
        pid = str(payment.get("payment_id") or "").strip()
        if pid:
            return pid
        auth = payment.get("authorization")
        if not isinstance(auth, dict) or auth.get("nonce") is None:
            return ""
        network = normalize_network_id(str(payment.get("network") or ""))
        asset = str(payment.get("asset") or X402_DEFAULT_ASSET).upper()
        entry = _pkg().resolve_asset_entry(network, asset)
        chain_id = _chain_id_for(network) or 0
        token = str(entry["contract"]).lower() if entry else ""
        return f"nonce:{chain_id}:{token}:{_nonce_hex(auth.get('nonce'))}"

    def _mark_pending(self, payment_id: str) -> None:
        self._pending_settlements[payment_id] = {
            "status": "pending",
            "started_at": time.time(),
        }
        self._trim(self._pending_settlements, self._max_pending)

    def _mark_settled(self, payment_id: str, tx_hash: str) -> None:
        entry = self._pending_settlements.get(payment_id)
        if entry is None:
            entry = {}
            self._pending_settlements[payment_id] = entry
        entry["status"] = "settled"
        entry["tx_hash"] = tx_hash
        entry["settled_at"] = time.time()
        self._settled_txs[payment_id] = tx_hash
        self._settled_txs.move_to_end(payment_id)
        self._trim(self._settled_txs, self._max_settled)

    def _mark_pending_failed(self, payment_id: str, code: str, detail: str) -> None:
        entry = self._pending_settlements.get(payment_id)
        if entry is None:
            entry = {}
            self._pending_settlements[payment_id] = entry
        entry["status"] = "failed"
        entry["error_code"] = code
        entry["error_detail"] = detail
        entry["failed_at"] = time.time()

    @staticmethod
    def _trim(ordered: OrderedDict[str, Any], max_size: int) -> None:
        while len(ordered) > max_size:
            ordered.popitem(last=False)

    @staticmethod
    def _normalize_address(value: str) -> str:
        try:
            return to_checksum_address(value)
        except (ValueError, TypeError):
            return value
