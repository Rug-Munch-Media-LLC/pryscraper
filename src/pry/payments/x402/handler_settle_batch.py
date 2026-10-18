"""Pry — batch settlement finalisation (``SettleMixin`` slice).

A batch settles as ONE on-chain tx but buys N operations, so access is gated
per operation. All-or-nothing: an unproven settlement leaves every item
unsettled, so no part of the batch may be served.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _batch_operations(batch: dict[str, Any]) -> list[str]:
    return [str(op) for op in (batch.get("operations") or []) if str(op).strip()]


def _batch_identity(
    batch: dict[str, Any], tx_hash: str, network: str, asset: str
) -> dict[str, str]:
    """Batch identity fields, with explicit arguments taking precedence."""
    return {
        "tx_hash": tx_hash or str(batch.get("tx_hash") or ""),
        "network": network or str(batch.get("network") or ""),
        "asset": asset or str(batch.get("asset") or ""),
        "caller_key": str(batch.get("caller_key") or ""),
    }


def _not_proven(batch_id: str, ops: list[str]) -> dict[str, Any]:
    """Fail-closed status when the stored settlement is missing or failed."""
    logger.warning(
        "x402_batch_settlement_not_proven",
        extra={"batch_id": batch_id, "operations": ops},
    )
    return {
        "batch_id": batch_id,
        "settled": [],
        "unsettled": ops,
        "all_settled": False,
        "written": 0,
    }


class BatchSettleMixin:
    """Batch finalisation for :class:`~pry.payments.x402.handler.X402Handler`."""

    def finalize_batch_settlement(
        self,
        batch_id: str,
        *,
        tx_hash: str = "",
        network: str = "",
        asset: str = "",
    ) -> dict[str, Any]:
        """Persist per-item receipts for a settled batch; return the gate status.

        A replayed settle finds the existing keys and writes nothing — each
        item is credited once — while still reporting every item as settled.
        """
        from pry.payments.x402.batch import store as batch_store

        batch = batch_store._load_batch(batch_id) or {}
        ops = _batch_operations(batch)
        settlement = batch.get("settlement") or {}
        if settlement.get("success") is not True:
            return _not_proven(batch_id, ops)
        recorded = self.record_batch_settlements(
            batch_id, ops, settlement, **_batch_identity(batch, tx_hash, network, asset)
        )
        recorded["batch_id"] = batch_id
        return recorded
