"""Pry — X402Handler settle mixin (public facade).

``settle_payment`` / ``settle_payment_strict`` with idempotent settlement
caching, retry/backoff and the settlement webhook. Batch finalisation lives in
``handler_settle_batch``; the retry/hook/ledger helpers in
``handler_settle_support`` — all re-exported here so existing imports and test
patch targets (``handler_settle.<name>``, ``handler_settle.asyncio.sleep``)
keep working.
"""

from __future__ import annotations

import asyncio  # noqa: F401 — patch surface: tests patch handler_settle.asyncio.sleep
import logging
from dataclasses import replace
from typing import Any

from pry.payments.x402.handler_settle_batch import BatchSettleMixin
from pry.payments.x402.handler_settle_flow import (
    _cached_settlement,
    _db_idempotent_cached,
    _finalize_receipt,
    _notify_success,
    _persist_settle,
    _pre_settle_aborted,
    _settle_locked,
)
from pry.payments.x402.handler_settle_support import (
    _enrich_record,
    _retry_after_seconds,
    _settle_context,
)
from pry.payments.x402.scheme import X402_PRICING, resolve_price_usd

logger = logging.getLogger(__name__)

__all__ = [
    "SettleError",
    "SettleMixin",
    "_db_idempotent_cached",
    "_enrich_record",
    "_resolve_amount",
    "_retry_after_seconds",
]


def _resolve_amount(
    payment_id: str,
    network: str,
    asset: str,
    amount_usd: float,
    operation: str,
) -> float:
    """Resolve the server-authoritative amount for the receipt."""
    if operation:
        amount_usd = resolve_price_usd(operation, network=network, asset=asset)
    if amount_usd <= 0:
        amount_usd = X402_PRICING.get(payment_id, {}).get("price_usd", 0.001)
    return amount_usd


class SettleError(Exception):
    """Payment settlement failed."""

    def __init__(self, reason: str, **extra: Any):
        self.reason = reason
        self.extra = extra
        super().__init__(reason)


class SettleMixin(BatchSettleMixin):
    """Payment settlement methods for X402Handler."""

    async def settle_payment(self, payment_id: str, tx_hash: str, **options: Any) -> dict[str, Any]:
        """Settle a payment via the facilitator router.

        ``options`` accepts ``network``, ``asset``, ``amount_usd`` and
        ``operation`` (the pre-split keyword arguments). Returns a settlement
        receipt (to be Base64-encoded in PAYMENT-RESPONSE header).
        """
        ctx = _settle_context(self, payment_id, tx_hash, options)
        ctx = replace(
            ctx,
            amount_usd=_resolve_amount(
                ctx.payment_id, ctx.network, ctx.asset, ctx.amount_usd, ctx.operation
            ),
        )
        # Serialize the check-then-settle sequence under _verify_lock to prevent
        # TOCTOU double-settle under concurrent requests (same lock as verify).
        with self._verify_lock:
            cached = _cached_settlement(self, ctx)
            if cached is not None:
                return cached
            aborted = _pre_settle_aborted(self, ctx)
            if aborted is not None:
                return aborted
            settlement, record = await _settle_locked(self, ctx)
        _persist_settle(self, record, ctx)
        if record.get("success") is True:
            await _notify_success(self, ctx, record)
        return _finalize_receipt(settlement, ctx)

    async def settle_payment_strict(
        self, payment_id: str, tx_hash: str, **options: Any
    ) -> dict[str, Any]:
        """Settle a payment, raising :class:`SettleError` on failure."""
        settlement = await self.settle_payment(payment_id, tx_hash, **options)
        if not (settlement or {}).get("success"):
            raise SettleError(
                (settlement or {}).get("reason", "settlement failed"),
                payment_id=payment_id,
                tx_hash=tx_hash,
                **options,
            )
        return settlement
