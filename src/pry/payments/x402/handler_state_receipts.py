"""Pry — X402Handler payment-receipt persistence (``StateMixin`` slice).

DB-first with a JSONL audit fallback. The DB is authoritative when reachable;
the file append is best-effort and never blocks the payment flow.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("pry.payments.x402.handler")


class ReceiptsMixin:
    """Payment records: load, append, refresh and single-payment lookup."""

    payments: list[dict[str, Any]]
    payments_file: Path
    _use_db: bool
    _loaded: bool
    _consumed_txs: set[str]

    def _ensure_loaded(self) -> None:
        """Load payment records on first use (idempotent)."""
        if self._loaded:
            return
        self._load_payments()
        self._loaded = True

    def _load_payments(self) -> None:
        self.payments = []
        self._consumed_txs = set()
        if self._load_payments_db():
            return
        self._load_payments_file()

    def _load_payments_db(self) -> bool:
        """Load from the DB (authoritative). False = fall back to the audit file."""
        if not self._use_db:
            return False
        try:
            from pry.payments.x402.ledger_store import get_payments

            self.payments = get_payments()
            self._consumed_txs = {
                p["tx_hash"] for p in self.payments if p.get("tx_hash") and p.get("verified")
            }
            return True
        except Exception as e:  # noqa: BLE001 — degrade to file mode
            logger.warning("x402_ledger_db_read_failed", extra={"error": str(e)[:160]})
            return False

    def _load_payments_file(self) -> None:
        if not self.payments_file.exists():
            return
        try:
            for line in self.payments_file.read_text().splitlines():
                if line.strip():
                    self._append_payment(json.loads(line))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("x402_state_load_failed", extra={"error": str(e)[:160]})

    def _append_payment(self, payment: dict[str, Any]) -> None:
        self.payments.append(payment)
        if payment.get("tx_hash") and payment.get("verified"):
            self._consumed_txs.add(payment["tx_hash"])

    def _record_payment(self, payment: dict[str, Any]) -> None:
        """Persist a payment record: DB (source of truth) + JSONL (audit trail)."""
        self._ensure_loaded()
        if self._use_db:
            try:
                from pry.payments.x402.ledger_store import record_payment

                record_payment(payment)
            except Exception as e:  # noqa: BLE001 — DB write failure degrades to file
                logger.warning("x402_payment_db_record_failed", extra={"error": str(e)[:160]})
        try:
            with open(self.payments_file, "a") as f:
                f.write(json.dumps(payment) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            logger.warning("x402_payment_record_failed", extra={"error": str(e)})
        self.payments.append(payment)
        if payment.get("tx_hash") and payment.get("verified"):
            self._consumed_txs.add(payment["tx_hash"])

    def refresh(self) -> None:
        """Reload payment records from the audit file (picks up other handlers)."""
        self._load_payments()
        self._loaded = True

    def _payment_caller_key(self, payment_id: str) -> str:
        """Caller key (API key → user) recorded on the payment, if known."""
        pid = str(payment_id or "").strip()
        if not pid:
            return ""
        self._ensure_loaded()
        for p in reversed(self.payments):
            if str(p.get("payment_id") or "") == pid:
                return str(p.get("caller_key") or "")
        return ""

    def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        for p in self.payments:
            if p["payment_id"] == payment_id:
                return p
        return None
