"""Pry — x402 facilitator settlement receipts (extracted from ``facilitator.py``).

Normalizes facilitator responses into standard settlement receipts and
builds the offline-mode settlement stub. Mixed into
:class:`~pry.payments.x402.facilitator.FacilitatorRouter` as
``SettleReceiptMixin``.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class SettleReceiptMixin:
    """Settlement receipt normalization for the x402 router."""

    def _normalize_settlement(
        self,
        data: dict[str, Any],
        payment_id: str,
        tx_hash: str,
        network: str,
        facilitator: str,
    ) -> dict[str, Any]:
        """Normalize facilitator response into a standard settlement receipt.

        An explicit ``success: false`` is a refusal — never upgrade it to a
        success receipt. Only the absence of the flag keeps legacy semantics.
        """
        raw_success = data.get("success")
        success = not (raw_success is False or raw_success == "false")
        return {
            "success": success,
            "transaction": tx_hash,
            "network": network,
            "payment_id": payment_id,
            "facilitator": facilitator,
            "settled_at": datetime.now(UTC).isoformat(),
            "block_number": data.get("blockNumber", data.get("block_number", "")),
            "block_hash": data.get("blockHash", data.get("block_hash", "")),
            "tx_index": data.get("transactionIndex", data.get("tx_index", "")),
            "confirmations": data.get("confirmations", 0),
            "amount_paid": data.get("amountPaid", data.get("amount_paid", "")),
            "receipt": data,
        }

    def _offline_settlement(self, payment_id: str, tx_hash: str, network: str) -> dict[str, Any]:
        return {
            "success": True,
            "transaction": tx_hash,
            "network": network,
            "payment_id": payment_id,
            "facilitator": "offline",
            "settled_at": datetime.now(UTC).isoformat(),
            "note": "Offline mode — settlement not verified on-chain",
        }
