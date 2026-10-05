"""Pry — X402Handler authorize/capture/void (escrow-lite) mixin.

Extracted from ``handler_verify`` (behavior-preserving): the authorize →
capture/void lifecycle that wraps :meth:`VerifyMixin.verify_payment`. Kept in
its own module so ``handler_verify`` stays within the file-size budget.
"""
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import time
from typing import Any


class AuthorizeMixin:
    """Authorize / capture / void payment methods for X402Handler."""

    async def authorize_payment(
        self,
        payment_id: str,
        tx_hash: str,
        network: str,
        asset: str,
        amount_usd: float = 0,
        caller_key: str = "",
        operation: str = "",
    ) -> dict[str, Any]:
        """Authorize a payment without capturing. Returns authorization record."""
        result = await self.verify_payment(
            payment_id, tx_hash, network, asset, amount_usd, caller_key, operation
        )
        if result.get("verified"):
            self._authorized_payments[payment_id] = {
                "tx_hash": tx_hash,
                "network": network,
                "asset": asset,
                "amount_usd": amount_usd,
                "authorized_at": time.time(),
            }
            return {"authorized": True, "payment_id": payment_id, "captured": False}
        return {"authorized": False, "reason": result.get("reason", "verification failed")}

    def capture_payment(self, payment_id: str) -> dict[str, Any]:
        """Capture a previously authorized payment."""
        auth = self._authorized_payments.pop(payment_id, None)
        if not auth:
            return {"success": False, "error": "no authorization found"}
        return {"success": True, "payment_id": payment_id, "captured": True}

    def void_payment(self, payment_id: str) -> dict[str, Any]:
        """Void a previously authorized payment without capturing."""
        self._authorized_payments.pop(payment_id, None)
        return {"success": True, "payment_id": payment_id, "voided": True}
