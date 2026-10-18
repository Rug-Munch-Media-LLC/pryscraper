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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def _is_receipt_for(record: Any, payment_id: str) -> bool:
    """True when ``record`` is a successful receipt bound to ``payment_id``."""
    return (
        isinstance(record, dict)
        and record.get("success") is True
        and str(record.get("payment_id") or "").strip() == payment_id
    )


def _memory_has_receipt(handler: Any, payment_id: str) -> bool:
    settled = getattr(handler, "_settled_txs", None)
    if not isinstance(settled, dict):
        return False
    return any(_is_receipt_for(rec, payment_id) for rec in settled.values())


def _jsonl_line_matches(line: str, payment_id: str) -> bool:
    if not line.strip():
        return False
    try:
        return _is_receipt_for(json.loads(line), payment_id)
    except json.JSONDecodeError:
        return False  # a torn audit line is not proof of settlement


def _jsonl_has_receipt(path: Any, payment_id: str) -> bool:
    if path is None:
        return False
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return False
    return any(_jsonl_line_matches(line, payment_id) for line in lines)


def _db_has_receipt(payment_id: str) -> bool:
    from pry.payments.x402.ledger_settlement import settlement_for_payment

    return _is_receipt_for(settlement_for_payment(payment_id), payment_id)


def _readers(handler: Any, payment_id: str) -> tuple[tuple[str, Callable[[], bool]], ...]:
    """Source name → fail-closed receipt reader, in canonical read order."""
    return (
        ("memory", lambda: _memory_has_receipt(handler, payment_id)),
        (
            "jsonl",
            lambda: _jsonl_has_receipt(getattr(handler, "settlements_file", None), payment_id),
        ),
        ("db", lambda: _db_has_receipt(payment_id)),
    )


def is_settled(handler: Any, payment_id: str) -> bool:
    """True only when a successful settlement receipt is bound to ``payment_id``.

    Fail closed: a missing identifier, an unreadable source, an absent receipt
    or an explicit ``success: false`` all return False.
    """
    pid = str(payment_id or "").strip()
    if not pid:
        return False

    for source, read in _readers(handler, pid):
        try:
            if read():
                return True
        except Exception as e:  # noqa: BLE001 — unreadable source must not grant access
            logger.warning(
                "x402_settlement_gate_read_failed",
                extra={"source": source, "payment_id": pid, "error": str(e)[:160]},
            )
    return False
