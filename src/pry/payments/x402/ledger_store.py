"""Postgres-backed x402 ledger storage (audit item #2, storage layer).
Replaces the JSONL files' semantics with a repository the handler can
adopt (PART 2 rewires the handler; this module is standalone):
- payments: insert-or-update by (payment_id, tx_hash); indexed lookups
  replace the O(n) in-memory scan.
- settlements: DB-enforced idempotency — a UNIQUE index on the settlement
  key (``tx:{network}:{tx_hash}``, fallback ``pid:{payment_id}``) makes a
  concurrent duplicate insert return the EXISTING receipt instead of
  writing a second one.
Records are stored losslessly in a JSON column (``record`` / ``receipt``)
with the hot fields promoted to indexed real columns. Same dict shapes as
the JSONL era, so call sites don't change shape.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_LEDGER_LIMIT: int = 10_000


class LedgerUnavailable(RuntimeError):
    """Raised when the DB is unreachable for a ledger write (fail loud)."""


def _parse_dt(value: str | None) -> Any:
    """ISO string → datetime (None-safe, tolerant)."""

    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError) as exc:
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_parse_dt"},
        )
        return None


def _iso(value: Any) -> str:

    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return str(value.isoformat())
    return str(value)


def record_payment(record: dict[str, Any]) -> None:
    """Insert-or-update a payment record keyed by (payment_id, tx_hash)."""
    from pry.core.db.models import X402PaymentRecord
    from pry.core.db.session import session_scope

    with session_scope() as session:
        row = (
            session.query(X402PaymentRecord)
            .filter_by(
                payment_id=str(record.get("payment_id", "")),
                tx_hash=str(record.get("tx_hash", "")),
            )
            .first()
        )
        if row is None:
            row = X402PaymentRecord(
                payment_id=str(record.get("payment_id", "")),
                tx_hash=str(record.get("tx_hash", "")),
            )
            session.add(row)
        row.network = str(record.get("network", ""))  # type: ignore[assignment]
        row.asset = str(record.get("asset", ""))  # type: ignore[assignment]
        try:
            row.amount_usd = float(record.get("amount_usd", 0.0))  # type: ignore[assignment]
        except (TypeError, ValueError) as exc:
            logger.warning(
                "payments_exception_swallowed",
                extra={"error": str(exc), "handler": "record_payment"},
            )
            row.amount_usd = 0.0  # type: ignore[assignment]
        row.required_amount_atomic = str(record.get("required_amount_atomic", ""))  # type: ignore[assignment]
        row.operation = str(record.get("operation", ""))  # type: ignore[assignment]
        row.verified = bool(record.get("verified", False))  # type: ignore[assignment]
        row.verified_at = _parse_dt(record.get("verified_at"))
        row.expires_at = _parse_dt(record.get("expires_at"))
        row.facilitator = str(record.get("facilitator", ""))  # type: ignore[assignment]
        row.caller_key = str(record.get("caller_key", ""))  # type: ignore[assignment]
        row.user_id = str(record.get("user_id") or record.get("caller_key", ""))  # type: ignore[assignment]
        row.reason = str(record.get("reason", ""))  # type: ignore[assignment]
        row.record = dict(record)  # type: ignore[assignment]


def get_payments(limit: int = _LEDGER_LIMIT) -> list[dict[str, Any]]:
    """Payment records, most-recent-first."""
    from pry.core.db.models import X402PaymentRecord
    from pry.core.db.session import session_scope

    with session_scope() as session:
        rows = (
            session.query(X402PaymentRecord)
            .order_by(X402PaymentRecord.id.desc())
            .limit(limit)
            .all()
        )
        return [dict(r.record or {}) for r in rows]


def payments_for(payment_id: str) -> list[dict[str, Any]]:
    """All records for one payment_id (id + tx variants)."""
    from pry.core.db.models import X402PaymentRecord
    from pry.core.db.session import session_scope

    with session_scope() as session:
        rows = (
            session.query(X402PaymentRecord)
            .filter_by(payment_id=payment_id)
            .order_by(X402PaymentRecord.id.desc())
            .all()
        )
        return [dict(r.record or {}) for r in rows]


def record_settlement(receipt: dict[str, Any], settle_key: str) -> dict[str, Any]:
    """Insert-or-return-existing a settlement receipt (DB-enforced idempotency).

    A UNIQUE index on ``settlement_key`` makes a concurrent duplicate insert
    fail; the race is handled by re-reading the existing row and returning
    it. Never raises on duplicates — the caller always gets a receipt.
    """
    from sqlalchemy.exc import IntegrityError, OperationalError
    from sqlalchemy.orm.exc import FlushError

    from pry.core.db.models import X402SettlementRecord
    from pry.core.db.session import session_scope

    with session_scope() as session:
        existing = session.query(X402SettlementRecord).filter_by(settlement_key=settle_key).first()
        if existing is not None:
            return dict(existing.receipt or {})
        try:
            session.add(
                X402SettlementRecord(
                    settlement_key=settle_key,
                    payment_id=str(receipt.get("payment_id", "")),
                    user_id=str(receipt.get("user_id", "")),
                    tx_hash=str(receipt.get("tx_hash") or receipt.get("transaction") or ""),
                    network=str(receipt.get("network", "")),
                    asset=str(receipt.get("asset", "")),
                    amount_usd=float(receipt.get("amount_usd", 0.0) or 0.0),
                    facilitator=str(receipt.get("facilitator", "")),
                    settled_at=_parse_dt(receipt.get("settled_at")),
                    receipt=dict(receipt),
                    success=bool(receipt.get("success", True)),
                )
            )
        except (IntegrityError, FlushError, OperationalError):
            session.rollback()
            row = session.query(X402SettlementRecord).filter_by(settlement_key=settle_key).first()
            if row is None:
                raise
            return dict(row.receipt or {})
    return dict(receipt)


def settlement_by_key(settle_key: str) -> dict[str, Any] | None:
    from pry.core.db.models import X402SettlementRecord
    from pry.core.db.session import session_scope

    with session_scope() as session:
        row = session.query(X402SettlementRecord).filter_by(settlement_key=settle_key).first()
        return dict(row.receipt or {}) if row is not None else None


def get_settlements(limit: int = _LEDGER_LIMIT) -> list[dict[str, Any]]:
    from pry.core.db.models import X402SettlementRecord
    from pry.core.db.session import session_scope

    with session_scope() as session:
        rows = (
            session.query(X402SettlementRecord)
            .order_by(X402SettlementRecord.id.desc())
            .limit(limit)
            .all()
        )
        return [dict(r.receipt or {}) for r in rows]


def available() -> bool:
    """True when the DB is reachable (the handler can adopt the DB path)."""
    try:
        from sqlalchemy import text

        from pry.core.db.session import session_scope

        with session_scope() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 — availability probe
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "available"},
        )
        return False
