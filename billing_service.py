"""Pry — prepaid balance billing service.

Credits (deposits, grants, x402 settlement receipts) and debits (metered
usage) against per-user USD balances with a full ledger. Every mutation is
atomic and records ``balance_after`` so the ledger can be replayed/audited.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from db import models as _models
from db.session import get_session

logger = logging.getLogger(__name__)

VALID_REASONS = {"deposit", "grant", "usage", "refund"}


class InsufficientBalance(Exception):
    """Raised when a drawdown would take the balance negative."""


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
            "balance_usd": round(float(row.balance_usd), 4),
            "low_balance": float(row.balance_usd) <= float(row.low_balance_threshold_usd),
            "low_balance_threshold_usd": float(row.low_balance_threshold_usd),
        }


def credit(user_id: str, amount_usd: float, *, reason: str, reference: str = "") -> dict[str, Any]:
    """Add funds. reason: deposit | grant | refund."""
    if reason not in ("deposit", "grant", "refund"):
        raise ValueError(f"'{reason}' is not a credit reason")
    if amount_usd <= 0:
        raise ValueError("credit amount must be positive")
    return _apply(user_id, amount_usd, reason, reference)


def drawdown(user_id: str, amount_usd: float, *, reference: str = "") -> dict[str, Any]:
    """Consume funds for metered usage. Raises InsufficientBalance."""
    if amount_usd <= 0:
        raise ValueError("drawdown amount must be positive")
    return _apply(user_id, -abs(amount_usd), "usage", reference)


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
                "delta_usd": round(float(r.delta_usd), 4),
                "reason": r.reason,
                "reference": r.reference,
                "balance_after": round(float(r.balance_after), 4),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def _apply(user_id: str, delta_usd: float, reason: str, reference: str) -> dict[str, Any]:
    if reason not in VALID_REASONS:
        raise ValueError(f"unknown ledger reason '{reason}'")
    from api_keys_service import ensure_user

    ensure_user(user_id)  # balances carry an FK to users
    with get_session() as session:
        row = session.query(_models.Balance).filter_by(user_id=user_id).with_for_update().first()
        current = float(row.balance_usd) if row else 0.0
        new_balance = round(current + delta_usd, 6)
        if new_balance < 0:
            raise InsufficientBalance(
                f"balance {current:.4f} USD cannot cover {-delta_usd:.4f} USD"
            )
        if row is None:
            row = _models.Balance(user_id=user_id, balance_usd=new_balance)
            session.add(row)
        else:
            row.balance_usd = new_balance
        session.add(
            _models.LedgerEntry(
                user_id=user_id,
                delta_usd=delta_usd,
                reason=reason,
                reference=reference,
                balance_after=new_balance,
            )
        )
        session.commit()
        logger.info(
            "billing_applied",
            extra={
                "user_id": user_id,
                "delta_usd": delta_usd,
                "reason": reason,
                "balance_after": new_balance,
            },
        )
        return {
            "user_id": user_id,
            "balance_usd": round(new_balance, 4),
            "low_balance": new_balance <= float(getattr(row, "low_balance_threshold_usd", 5.0)),
        }
