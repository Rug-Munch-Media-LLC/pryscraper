"""Pry — human-readable invoice numbering + tax computation.

Invoice numbers are ``INV-YYYYMM-NNNNNN`` (six-digit, non-resetting global
counter per calendar month). The counter lives in the ``invoice_number_sequences``
table and is advanced by a single atomic ``INSERT ... ON CONFLICT ... RETURNING``
statement — never ``max(id) + 1``, which races between workers and reissues a
number after a delete.

Tax is computed at invoice creation and stored as ``Decimal``. ``tax_rate`` is a
fraction (``0.20`` = 20 %%). ``reverse_charge`` (EU B2B) forces zero tax and is
recorded on the invoice. Paid invoices are immutable: :func:`apply_tax` refuses
to recompute tax once the invoice is paid.

SPDX-License-Identifier: MIT — Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pry.core.db import models as _models
from pry.core.db.session import session_scope

logger = logging.getLogger(__name__)

INVOICE_PREFIX = "INV"
SEQ_WIDTH = 6
_TAX_QUANT = Decimal("0.000001")
_ZERO = Decimal("0")
PAID_STATUSES = frozenset({"paid"})
#: Columns that may never change after payment.
IMMUTABLE_AFTER_PAID = ("amount_usd", "tax_amount", "tax_rate", "tax_country", "reverse_charge")


class InvoiceNumberError(RuntimeError):
    """Raised when a number cannot be allocated or assigned."""


def _dec(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def period_for(when: datetime | None = None) -> str:
    """``YYYYMM`` period for *when* (UTC, defaults to now)."""
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y%m")


_ALLOCATE_SQL = text(
    "INSERT INTO invoice_number_sequences (period, last_value) VALUES (:period, 1) "
    "ON CONFLICT (period) DO UPDATE "
    "SET last_value = invoice_number_sequences.last_value + 1 "
    "RETURNING last_value"
)


def allocate_invoice_number(period: str | None = None, *, session: Any | None = None) -> str:
    """Atomically allocate the next ``INV-YYYYMM-NNNNNN`` number.

    The upsert+returning statement is the concurrency boundary: two workers
    racing on the same period get different values because the database
    serialises the row update, and a unique index on ``invoice_number`` is the
    final backstop.
    """
    key = period or period_for()
    if session is not None:
        return _allocate(key, session)
    with session_scope() as own:
        return _allocate(key, own)


def _allocate(period: str, session: Any) -> str:
    value = session.execute(_ALLOCATE_SQL, {"period": period}).scalar_one_or_none()
    if value is None:  # pragma: no cover — RETURNING is supported on both dialects
        raise InvoiceNumberError(f"sequence allocation returned no value for {period}")
    logger.info("invoice_number_allocated", extra={"period": period, "seq": int(value)})
    return f"{INVOICE_PREFIX}-{period}-{int(value):0{SEQ_WIDTH}d}"


def assign_invoice_number(invoice_id: str) -> str:
    """Assign (once) the persistent number of a stored hosting invoice."""
    with session_scope() as session:
        row = (
            session.query(_models.HostingInvoice)
            .filter_by(invoice_id=invoice_id)
            .with_for_update()
            .first()
        )
        if row is None:
            raise InvoiceNumberError(f"unknown invoice {invoice_id!r}")
        if row.invoice_number:
            return str(row.invoice_number)
        period = period_for(row.created_at) if row.created_at is not None else period_for()
        row.invoice_number = allocate_invoice_number(period, session=session)
        return str(row.invoice_number)


def number_subscription_invoice(record: dict[str, Any]) -> str | None:
    """Attach a number to an in-memory subscription invoice record.

    Best-effort by design: the subscription registry must keep working when no
    database is wired (unit tests / bare dev). A DB error is logged and the
    invoice is emitted without a number rather than failing checkout.
    """
    existing = record.get("invoice_number")
    if existing:
        return str(existing)
    try:
        number = allocate_invoice_number(period_for())
    except (SQLAlchemyError, InvoiceNumberError) as exc:
        logger.warning("invoice_number_unavailable", extra={"error": str(exc)})
        return None
    record["invoice_number"] = number
    return number


def compute_tax(
    amount_usd: Any,
    tax_rate: Any = 0,
    tax_country: str = "",
    *,
    reverse_charge: bool = False,
) -> dict[str, Any]:
    """Compute tax for *amount_usd* at fractional *tax_rate*.

    Returns exact ``Decimal`` values: ``tax_amount``, ``tax_rate``,
    ``tax_country``, ``reverse_charge`` and ``total_usd``. A reverse-charge
    (EU B2B) invoice carries zero tax and rate zero.
    """
    base = _dec(amount_usd)
    if base < _ZERO:
        raise ValueError("amount_usd must be >= 0")
    rate = _ZERO if reverse_charge else _dec(tax_rate)
    if rate < _ZERO:
        raise ValueError("tax_rate must be >= 0")
    tax = (base * rate).quantize(_TAX_QUANT, rounding=ROUND_HALF_UP)
    return {
        "tax_amount": tax,
        "tax_rate": rate,
        "tax_country": (tax_country or "").upper()[:2],
        "reverse_charge": bool(reverse_charge),
        "total_usd": (base + tax).quantize(_TAX_QUANT, rounding=ROUND_HALF_UP),
    }


def apply_tax(
    record: dict[str, Any],
    tax_rate: Any = 0,
    tax_country: str = "",
    *,
    reverse_charge: bool = False,
) -> dict[str, Any]:
    """Return *record* with tax fields applied; refuses paid invoices."""
    if str(record.get("status", "")).lower() in PAID_STATUSES:
        raise ValueError("paid invoices are immutable — tax cannot be recomputed")
    tax = compute_tax(
        record.get("amount_usd", 0), tax_rate, tax_country, reverse_charge=reverse_charge
    )
    updated = dict(record)
    updated.update(
        {
            "tax_amount": tax["tax_amount"],
            "tax_rate": tax["tax_rate"],
            "tax_country": tax["tax_country"],
            "reverse_charge": tax["reverse_charge"],
            "total_usd": tax["total_usd"],
        }
    )
    return updated
