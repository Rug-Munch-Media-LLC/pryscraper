"""Pry — X402Handler batch receipt writer (``StateMixin`` slice).

One on-chain batch tx buys N operations, so each ``(batch_id, operation)`` gets
its own idempotent receipt that the settlement gate can prove individually.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pry.payments.x402.handler_state_ledger import batch_item_payment_id, batch_reference
from pry.payments.x402.scheme import X402_PRICING

logger = logging.getLogger("pry.payments.x402.handler")

_OPTION_KEYS = frozenset({"tx_hash", "network", "asset", "caller_key"})


@dataclass
class BatchSettlementRequest:
    """Inputs for writing one receipt per batch item."""

    batch_id: str
    operations: list[str] = field(default_factory=list)
    settlement: dict[str, Any] = field(default_factory=dict)
    tx_hash: str = ""
    network: str = ""
    asset: str = ""
    caller_key: str = ""


def _clean_operations(operations: list[str] | None) -> list[str]:
    return [str(op) for op in (operations or []) if str(op).strip()]


def _identity(options: dict[str, Any], settlement: dict[str, Any], key: str, fallback: str = "") -> str:
    """Explicit option wins, then the settlement record, then a fallback field."""
    return str(options.get(key) or settlement.get(key) or fallback)


def _batch_request(
    batch_id: str,
    operations: list[str] | None,
    settlement: dict[str, Any] | None,
    options: dict[str, Any],
) -> BatchSettlementRequest:
    """Normalise the public kwargs into a :class:`BatchSettlementRequest`."""
    unknown = set(options) - _OPTION_KEYS
    if unknown:
        raise TypeError(f"unexpected batch settlement options: {sorted(unknown)}")
    settlement = settlement or {}
    return BatchSettlementRequest(
        batch_id=batch_id,
        operations=_clean_operations(operations),
        settlement=settlement,
        tx_hash=_identity(options, settlement, "tx_hash", str(settlement.get("transaction") or "")),
        network=_identity(options, settlement, "network"),
        asset=_identity(options, settlement, "asset"),
        caller_key=_identity(options, settlement, "caller_key", str(settlement.get("user_id") or "")),
    )


def _batch_item_record(req: BatchSettlementRequest, operation: str) -> dict[str, Any]:
    """The per-item settlement record (one on-chain tx, one operation)."""
    record = dict(req.settlement)
    record.update(
        {
            "payment_id": batch_item_payment_id(req.batch_id, operation),
            "batch_id": req.batch_id,
            "operation": operation,
            "success": True,
            "tx_hash": req.tx_hash,
            "network": req.network,
            "asset": req.asset,
            "amount_usd": X402_PRICING.get(operation, {}).get("price_usd", 0.0),
            "reference": batch_reference(req.batch_id, operation),
            "user_id": req.caller_key,
        }
    )
    return record


def _batch_result(
    settled: list[str], unsettled: list[str], all_settled: bool, written: int
) -> dict[str, Any]:
    return {
        "settled": settled,
        "unsettled": unsettled,
        "all_settled": all_settled,
        "written": written,
    }


class BatchStateMixin:
    """Batch receipt writer + per-item settlement status."""

    _settled_txs: dict[str, dict[str, Any]]

    def record_batch_settlements(
        self,
        batch_id: str,
        operations: list[str],
        settlement: dict[str, Any] | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        """Write ONE idempotent settlement receipt per batch item.

        Replay-safe by construction: an existing key is skipped, so a replayed
        batch settle credits each item exactly once. A settlement that is not
        explicitly ``success: True`` writes nothing and returns every item
        unsettled. ``options`` accepts ``tx_hash``, ``network``, ``asset`` and
        ``caller_key`` (the pre-split keyword arguments).
        """
        req = _batch_request(batch_id, operations, settlement, options)
        if not req.operations or req.settlement.get("success") is not True:
            return _batch_result([], req.operations, False, 0)
        self._ensure_loaded()
        written = self._write_batch_items(req)
        return _batch_result(req.operations, [], True, written)

    def _write_batch_items(self, req: BatchSettlementRequest) -> int:
        written = 0
        for op in req.operations:
            record = _batch_item_record(req, op)
            key = self._settlement_key(record)
            if key and key in self._settled_txs:
                continue  # replay → the item is already credited exactly once
            self._record_settlement(record)
            if key:
                self._settled_txs.setdefault(key, record)
            written += 1
        return written

    def batch_settlement_status(self, batch_id: str) -> dict[str, Any]:
        """Per-item settlement proof for a batch (all-or-nothing gate)."""
        from pry.payments.x402.batch import store as batch_store
        from pry.payments.x402.settlement_gate import is_settled

        batch = batch_store._load_batch(batch_id) or {}
        ops = [str(op) for op in (batch.get("operations") or []) if str(op).strip()]
        settled: list[str] = []
        unsettled: list[str] = []
        for op in ops:
            lookup = batch_item_payment_id(batch_id, op)
            (settled if is_settled(self, lookup) else unsettled).append(op)
        return {
            "batch_id": batch_id,
            "operations": ops,
            "settled": settled,
            "unsettled": unsettled,
            "all_settled": bool(ops) and not unsettled,
        }
