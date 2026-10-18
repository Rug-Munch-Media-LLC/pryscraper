"""Pry — DB read side of the x402 settlement gate.

The ledger is authoritative across processes and hosts; the in-memory index
and the JSONL audit trail are process-local/append-only fallbacks. This module
exposes exactly one lookup so the gate can ask "did THIS payment_id settle?"
without pulling the whole ledger.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from typing import Any


def settlement_for_payment(payment_id: str) -> dict[str, Any] | None:
    """Return the latest settlement receipt for ``payment_id``, or None.

    Errors are NOT swallowed: the caller must fail closed rather than treat
    an unreadable ledger as proof of settlement.
    """
    pid = str(payment_id or "").strip()
    if not pid:
        return None
    from pry.core.db.models import X402SettlementRecord
    from pry.core.db.session import session_scope

    with session_scope() as session:
        row = (
            session.query(X402SettlementRecord)
            .filter_by(payment_id=pid)
            .order_by(X402SettlementRecord.id.desc())
            .first()
        )
        if row is None:
            return None
        receipt = dict(row.receipt or {})
        # The receipt JSON is lossless, but older rows may predate it.
        if "success" not in receipt:
            receipt["success"] = row.success
        return receipt
