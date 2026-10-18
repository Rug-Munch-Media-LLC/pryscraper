"""Pry — X402Handler settlement ledger + replay indexes (``StateMixin`` slice).

Owns the settlement audit trail, the idempotency key shape and the settled-tx
index. Batch item identities live here because the settlement key is what makes
one on-chain batch tx prove N per-operation receipts.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("pry.payments.x402.handler")

BATCH_ITEM_SEP = ":"


def batch_item_payment_id(batch_id: str, operation: str) -> str:
    """Stable pseudo ``payment_id`` carrying one batch item's settlement receipt.

    A batch is one on-chain tx but N purchased operations. Serving is gated per
    operation, so each ``(batch_id, operation)`` needs its own receipt that the
    settlement gate can look up by ``payment_id``.
    """
    return f"{str(batch_id or '').strip()}{BATCH_ITEM_SEP}{str(operation or '').strip()}"


def batch_reference(batch_id: str, operation: str) -> str:
    """Ledger-style idempotency reference for one batch item (migration 0011 shape)."""
    return f"x402:batch:{str(batch_id or '').strip()}:{str(operation or '').strip()}"


@dataclass(frozen=True)
class _SettlementParts:
    """Identity fields a settlement key is built from."""

    tx_hash: str
    network: str
    batch_id: str
    operation: str
    payment_id: str


def _settlement_parts(rec: dict[str, Any] | None) -> _SettlementParts:
    rec = rec or {}
    return _SettlementParts(
        tx_hash=str(rec.get("tx_hash") or rec.get("transaction") or "").strip(),
        network=str(rec.get("network") or "").strip(),
        batch_id=str(rec.get("batch_id") or "").strip(),
        operation=str(rec.get("operation") or "").strip(),
        payment_id=str(rec.get("payment_id") or "").strip(),
    )


def _batch_settlement_key(parts: _SettlementParts) -> str:
    """One receipt per batch ITEM: the tx alone collides across N operations."""
    if parts.tx_hash:
        return f"batch:{parts.network}:{parts.tx_hash}:{parts.operation}"
    return batch_reference(parts.batch_id, parts.operation)


def _single_settlement_key(parts: _SettlementParts) -> str:
    if parts.tx_hash:
        return f"tx:{parts.network}:{parts.tx_hash}"
    return f"pid:{parts.payment_id}" if parts.payment_id else ""


class LedgerMixin:
    """Settlement persistence, idempotency keys and the settled-tx index."""

    settlements_file: Path
    _use_db: bool
    _settled_txs: dict[str, dict[str, Any]]

    def _record_settlement(self, settlement: dict[str, Any]) -> None:
        """Persist a settlement: DB (source of truth) + JSONL (audit trail)."""
        settlement.setdefault(
            "user_id", self._payment_caller_key(str(settlement.get("payment_id") or ""))
        )
        if self._use_db:
            try:
                from pry.payments.x402.ledger_store import record_settlement

                key = self._settlement_key(settlement)
                if key:
                    record_settlement(settlement, key)
            except Exception as e:  # noqa: BLE001 — degrade to file-only
                logger.warning("x402_settlement_db_record_failed", extra={"error": str(e)[:160]})
        try:
            with open(self.settlements_file, "a") as f:
                f.write(json.dumps(settlement) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            logger.warning("x402_settlement_record_failed", extra={"error": str(e)})

    def _load_settlements(self) -> None:
        """Rehydrate the settled-tx idempotency index (DB-first, JSONL fallback)."""
        self._settled_txs: dict[str, dict[str, Any]] = {}
        if self._load_settlements_db():
            return
        self._load_settlements_file()

    def _load_settlements_db(self) -> bool:
        if not self._use_db:
            return False
        try:
            from pry.payments.x402.ledger_store import get_settlements

            for rec in get_settlements():
                self._index_settlement(rec)
            return True
        except Exception as e:  # noqa: BLE001 — degrade to file mode
            logger.warning("x402_settlement_db_read_failed", extra={"error": str(e)[:160]})
            return False

    def _load_settlements_file(self) -> None:
        if not self.settlements_file.exists():
            return
        try:
            for line in self.settlements_file.read_text().splitlines():
                if line.strip():
                    self._index_settlement(json.loads(line))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("x402_state_load_failed", extra={"error": str(e)[:160]})

    def _index_settlement(self, rec: dict[str, Any]) -> None:
        """Index only *successful* settlements so a failed attempt can retry."""
        if rec.get("success") is not True:
            return
        key = self._settlement_key(rec)
        if key:
            self._settled_txs.setdefault(key, rec)

    def _settlement_key(self, rec: dict[str, Any] | None) -> str:
        """Stable idempotency key: ``batch:`` per item, else ``tx:``, else ``pid:``."""
        parts = _settlement_parts(rec)
        if parts.batch_id and parts.operation:
            return _batch_settlement_key(parts)
        return _single_settlement_key(parts)

    def _tx_consumed(self, tx_hash: str) -> bool:
        """True when ``tx_hash`` was already recorded as a *verified* payment."""
        if not tx_hash:
            return False
        self._ensure_loaded()
        return tx_hash in self._consumed_txs
