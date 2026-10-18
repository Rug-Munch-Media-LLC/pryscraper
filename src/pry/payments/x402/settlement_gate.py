"""Pry — fail-closed x402 settlement gate.

A payment that verified but never SETTLED must not buy access. ``is_paid``
proves verification only; this gate proves a successful settlement receipt is
bound to the SAME ``payment_id`` before a request is served.

Read order: in-memory settled index → JSONL audit trail → DB ledger. Any row
whose ``success`` is not exactly ``True`` (or that belongs to another payment)
is not proof. Read errors fail CLOSED.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def is_settled(handler: Any, payment_id: str) -> bool:
    """True only when a successful settlement receipt is bound to ``payment_id``.

    Fail closed: a missing identifier, an unreadable source, an absent receipt
    or an explicit ``success: false`` all return False.
    """
    pid = str(payment_id or "").strip()
    if not pid:
        return False

    def _match(rec: Any) -> bool:
        return (
            isinstance(rec, dict)
            and rec.get("success") is True
            and str(rec.get("payment_id") or "").strip() == pid
        )

    def _from_memory() -> bool:
        settled = getattr(handler, "_settled_txs", None)
        if not isinstance(settled, dict):
            return False
        return any(_match(rec) for rec in settled.values())

    def _from_jsonl() -> bool:
        path = getattr(handler, "settlements_file", None)
        if path is None:
            return False
        try:
            lines = path.read_text().splitlines()
        except FileNotFoundError:
            return False
        for line in lines:
            if not line.strip():
                continue
            try:
                if _match(json.loads(line)):
                    return True
            except json.JSONDecodeError:
                continue  # a torn audit line is not proof of settlement
        return False

    def _from_db() -> bool:
        from pry.payments.x402.ledger_settlement import settlement_for_payment

        return _match(settlement_for_payment(pid))

    for source, read in (("memory", _from_memory), ("jsonl", _from_jsonl), ("db", _from_db)):
        try:
            if read():
                return True
        except Exception as e:  # noqa: BLE001 — unreadable source must not grant access
            logger.warning(
                "x402_settlement_gate_read_failed",
                extra={"source": source, "payment_id": pid, "error": str(e)[:160]},
            )
    return False
