"""Money primitives for Pry's prepaid ledger.

Split out of :mod:`pry.commerce.billing_service` so that module stays under
the 200-line cap and so every ledger writer uses ONE Decimal coercion and ONE
read path.

``Decimal(str(x))`` — never ``Decimal(float)`` — because the latter imports the
binary residue the ledger is trying to avoid. Columns are ``NUMERIC(18,6)``;
floats appear only at the JSON boundary.

SPDX-License-Identifier: MIT — Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pry.core.db import models as _models
from pry.core.db.session import get_session

QUANT = Decimal("0.000001")
ZERO = Decimal("0")


def dec(value: Any) -> Decimal:
    """Coerce money to an exact 6-dp Decimal.

    Booleans are rejected because ``True`` would silently credit one dollar.
    """
    if isinstance(value, bool):
        raise ValueError("money value must be numeric, not bool")
    if isinstance(value, Decimal):
        raw = value
    else:
        try:
            raw = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid money value: {value!r}") from exc
    if not raw.is_finite():
        raise ValueError(f"invalid money value: {value!r}")
    return raw.quantize(QUANT, rounding=ROUND_HALF_UP)


def money(value: Any) -> float | None:
    """Decimal column -> JSON float (None stays None)."""
    return None if value is None else float(dec(value))


def get_balance(user_id: str) -> dict[str, Any]:
    """Return the current balance + low-balance flag (zero if no row)."""
    with get_session() as session:
        row = session.query(_models.Balance).filter_by(user_id=user_id).first()
        if row is None:
            return {
                "user_id": user_id,
                "balance_usd": 0.0,
                "low_balance": False,
                "low_balance_threshold_usd": 5.0,
            }
        return {
            "user_id": user_id,
            "balance_usd": money(row.balance_usd),
            "low_balance": dec(row.balance_usd) <= dec(row.low_balance_threshold_usd),
            "low_balance_threshold_usd": money(row.low_balance_threshold_usd),
        }


def ledger(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Most-recent ledger entries for a user."""
    with get_session() as session:
        rows = (
            session.query(_models.LedgerEntry)
            .filter_by(user_id=user_id)
            .order_by(_models.LedgerEntry.created_at.desc(), _models.LedgerEntry.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "delta_usd": money(r.delta_usd),
                "reason": r.reason,
                "reference": r.reference,
                "balance_after": money(r.balance_after),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
