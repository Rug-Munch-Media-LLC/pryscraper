"""Pry — prepaid balance mutations (credit / drawdown) on an exact ledger.

Money is ``Decimal`` end to end: inputs are coerced at the boundary with
``Decimal(str(x))`` (never ``Decimal(float)``), arithmetic is exact at 6 dp,
and the columns are ``NUMERIC(18,6)``. Floats appear only in JSON payloads.
The read side and the Decimal primitives live in
:mod:`pry.commerce.billing.billing_service`.

Idempotency: a non-empty ``reference`` identifies a credit. Two workers
crediting the same ``(user_id, reason, reference)`` produce ONE ledger row and
ONE balance delta — the partial unique index is the arbiter and this service
treats the loser's IntegrityError as "already applied".

SPDX-License-Identifier: MIT — Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError

from pry.commerce.billing.billing_service import (
    QUANT,
    ZERO,
    dec,
    get_balance,
    ledger,
    money,
)
from pry.core.db import models as _models
from pry.core.db.session import get_session

__all__ = [
    "InsufficientBalance",
    "credit",
    "drawdown",
    "get_balance",
    "ledger",
]

logger = logging.getLogger(__name__)

VALID_REASONS = {"deposit", "grant", "usage", "refund"}
CREDIT_REASONS = ("deposit", "grant", "refund")


class InsufficientBalance(Exception):
    """Raised when a drawdown would take the balance negative."""


def credit(
    user_id: str, amount_usd: float | Decimal | str, *, reason: str, reference: str = ""
) -> dict[str, Any]:
    """Add funds. reason: deposit | grant | refund. Idempotent per reference."""
    if reason not in CREDIT_REASONS:
        raise ValueError(f"'{reason}' is not a credit reason")
    amount = dec(amount_usd)
    if amount <= ZERO:
        raise ValueError("credit amount must be positive")
    return _apply(user_id, amount, reason, reference)


def drawdown(
    user_id: str, amount_usd: float | Decimal | str, *, reference: str = ""
) -> dict[str, Any]:
    """Consume funds for metered usage. Raises InsufficientBalance."""
    amount = dec(amount_usd)
    if amount <= ZERO:
        raise ValueError("drawdown amount must be positive")
    return _apply(user_id, -amount, "usage", reference)


def _find_entry(session: Any, user_id: str, reason: str, reference: str) -> Any:
    """The ledger row already holding this idempotency key (None if blank)."""
    if not reference:
        return None
    return (
        session.query(_models.LedgerEntry)
        .filter_by(user_id=user_id, reason=reason, reference=reference)
        .first()
    )


def _entry_payload(user_id: str, entry: _models.LedgerEntry, session: Any) -> dict[str, Any]:
    balance = session.query(_models.Balance).filter_by(user_id=user_id).first()
    threshold = dec(balance.low_balance_threshold_usd) if balance is not None else dec(5)
    after = dec(entry.balance_after)
    return {
        "user_id": user_id,
        "balance_usd": money(after),
        "low_balance": after <= threshold,
        "duplicate": True,
    }


def _existing_payload(user_id: str, reason: str, reference: str) -> dict[str, Any] | None:
    """Re-read the winner's committed row after our own insert lost."""
    if not reference:
        return None
    with get_session() as session:
        entry = _find_entry(session, user_id, reason, reference)
        return None if entry is None else _entry_payload(user_id, entry, session)


def _apply(user_id: str, delta: Decimal, reason: str, reference: str) -> dict[str, Any]:
    if reason not in VALID_REASONS:
        raise ValueError(f"unknown ledger reason '{reason}'")
    from pry.core.api_keys_service import ensure_user

    ensure_user(user_id)  # balances carry an FK to users
    # Attempt 2 runs only when a concurrent writer won the *balance-row* race
    # with a different reference; an idempotency loser is returned, not retried.
    for attempt in (1, 2):
        try:
            return _apply_once(user_id, delta, reason, reference)
        except IntegrityError:
            existing = _existing_payload(user_id, reason, reference)
            if existing is not None:
                logger.info(
                    "billing_credit_duplicate",
                    extra={"user_id": user_id, "reason": reason, "reference": reference},
                )
                return existing
            if attempt == 2:
                raise
    raise RuntimeError("unreachable: ledger apply loop exhausted")  # pragma: no cover


def _apply_once(user_id: str, delta: Decimal, reason: str, reference: str) -> dict[str, Any]:
    with get_session() as session:
        entry = _find_entry(session, user_id, reason, reference)
        if entry is not None:
            return _entry_payload(user_id, entry, session)

        row = session.query(_models.Balance).filter_by(user_id=user_id).with_for_update().first()
        current = dec(row.balance_usd) if row is not None else ZERO
        new_balance = (current + delta).quantize(QUANT, rounding=ROUND_HALF_UP)
        if new_balance < ZERO:
            raise InsufficientBalance(f"balance {current:.4f} USD cannot cover {-delta:.4f} USD")
        if row is None:
            row = _models.Balance(user_id=user_id, balance_usd=new_balance)
            session.add(row)
        else:
            row.balance_usd = new_balance
        session.add(
            _models.LedgerEntry(
                user_id=user_id,
                delta_usd=delta,
                reason=reason,
                reference=reference,
                balance_after=new_balance,
            )
        )
        session.commit()
        raw_threshold = getattr(row, "low_balance_threshold_usd", None)
        threshold = dec(raw_threshold) if raw_threshold is not None else dec(5)
        logger.info(
            "billing_applied",
            extra={
                "user_id": user_id,
                "delta_usd": str(delta),
                "reason": reason,
                "balance_after": str(new_balance),
            },
        )
        return {
            "user_id": user_id,
            "balance_usd": money(new_balance),
            "low_balance": new_balance <= threshold,
        }
