"""Pry — invoice refunds (negative ledger entry, idempotent per invoice).

A refund reverses revenue for a *paid* hosting invoice:

- amount must be ``> 0`` and ``<=`` the invoice's paid amount;
- one ledger row with ``reason='refund'`` and the unique reference
  ``refund:<invoice_id>`` is written — a second call returns that row and
  changes nothing (the partial unique index is the database arbiter);
- the invoice becomes ``refunded`` (full) or ``partially_refunded``;
- the ledger delta is **negative**: the refund claws the amount back out of
  the customer balance, which may therefore go negative (a receivable). This
  is deliberate — a prepaid balance row is not a substitute for the invoice.

SPDX-License-Identifier: MIT — Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError

from pry.commerce.billing.billing_service import QUANT, money
from pry.core.db import models as _models
from pry.core.db.session import get_session

logger = logging.getLogger(__name__)

REFUND_REASON = "refund"


class RefundError(ValueError):
    """Raised when a refund request is invalid for the invoice state."""


def refund_reference(invoice_id: str) -> str:
    """The idempotency reference for an invoice's refund."""
    return f"{REFUND_REASON}:{invoice_id}"


def _dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _existing(user_id: str, reference: str) -> _models.LedgerEntry | None:
    with get_session() as session:
        return (
            session.query(_models.LedgerEntry)
            .filter_by(user_id=user_id, reason=REFUND_REASON, reference=reference)
            .first()
        )


def _result(
    invoice: _models.HostingInvoice, entry: _models.LedgerEntry, *, duplicate: bool
) -> dict:
    return {
        "invoice_id": invoice.invoice_id,
        "status": invoice.status,
        "refunded_amount": money(-_dec(entry.delta_usd)),
        "reference": entry.reference,
        "duplicate": duplicate,
    }


def refund_invoice(invoice_id: str, amount: Any, reason: str = "") -> dict[str, Any]:
    """Refund *amount* USD of a paid invoice. Idempotent per invoice."""
    reference = refund_reference(invoice_id)
    session = get_session()
    try:
        invoice = (
            session.query(_models.HostingInvoice)
            .filter_by(invoice_id=invoice_id)
            .with_for_update()
            .first()
        )
        if invoice is None:
            raise RefundError(f"unknown invoice {invoice_id!r}")
        paid = _dec(invoice.amount_usd)
        refund = paid if amount is None else _dec(amount)
        if refund <= 0:
            raise RefundError("refund amount must be > 0")
        if refund > paid:
            raise RefundError(f"refund {refund} exceeds paid amount {paid}")
        if not invoice.user_id:
            raise RefundError("invoice has no user to credit the reversal to")

        existing = (
            session.query(_models.LedgerEntry)
            .filter_by(user_id=invoice.user_id, reason=REFUND_REASON, reference=reference)
            .first()
        )
        if existing is not None:
            return _result(invoice, existing, duplicate=True)

        from pry.core.api_keys_service import ensure_user

        ensure_user(str(invoice.user_id))
        balance = (
            session.query(_models.Balance)
            .filter_by(user_id=invoice.user_id)
            .with_for_update()
            .first()
        )
        current = _dec(balance.balance_usd) if balance is not None else Decimal("0")
        after = (current - refund).quantize(QUANT, rounding=ROUND_HALF_UP)
        if balance is None:
            balance = _models.Balance(user_id=str(invoice.user_id), balance_usd=after)
            session.add(balance)
        else:
            balance.balance_usd = after

        entry = _models.LedgerEntry(
            user_id=str(invoice.user_id),
            delta_usd=-refund,
            reason=REFUND_REASON,
            reference=reference,
            balance_after=after,
        )
        session.add(entry)
        invoice.status = "refunded" if refund == paid else "partially_refunded"
        payment = dict(invoice.payment or {})
        payment.update(
            {
                "refund_reason": str(reason or ""),
                "refunded_amount": str(refund),
                "refund_reference": reference,
            }
        )
        invoice.payment = payment
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            winner = _existing(str(invoice.user_id), reference)
            if winner is None:
                raise
            return _result(invoice, winner, duplicate=True)
        logger.info(
            "invoice_refunded",
            extra={"invoice_id": invoice_id, "amount": str(refund), "status": invoice.status},
        )
        return _result(invoice, entry, duplicate=False)
    finally:
        session.close()
