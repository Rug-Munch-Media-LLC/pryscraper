# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Invoice persistence for hosting signups/renewals (hosting_invoices table).

Audit item #1: invoices are durable rows, not in-memory dicts. Also hosts the
shared time helpers every hosting submodule monkeypatches in tests.
"""

from __future__ import annotations

import calendar
import logging
import os
from datetime import UTC, datetime
from typing import Any

from pry.core.db import models as _models
from pry.core.db.session import session_scope

logger = logging.getLogger("pry.commerce.hosting")

#: Invoice validity in seconds (default 24h).
ENV_HOSTING_INVOICE_TTL: str = "PRY_HOSTING_INVOICE_TTL"
_DEFAULT_INVOICE_TTL: int = 86_400


# ── Time helpers (monkeypatchable for tests) ────────────────────────────────
def _now() -> datetime:
    """Current UTC timestamp (single hook so tests can freeze time)."""
    return datetime.now(UTC)


def _utc_iso(dt: datetime) -> str:
    """ISO-8601 with explicit UTC offset (round-trips via fromisoformat)."""
    return dt.isoformat()


def _parse_iso(value: str) -> datetime:
    """Parse a stored ISO timestamp back into an aware datetime."""
    return datetime.fromisoformat(value)


def _add_months(dt: datetime, months: int) -> datetime:
    """Add whole calendar months to *dt*, clamping the day-of-month."""
    month_index = dt.year * 12 + (dt.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _aware(dt: datetime | None) -> datetime:
    """Normalize a possibly-naive DB datetime to aware UTC."""
    if dt is None:
        return _now()
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _invoice_ttl_seconds() -> int:
    """Invoice validity window (env override, default 24h)."""
    try:
        value = int(str(os.environ.get(ENV_HOSTING_INVOICE_TTL, _DEFAULT_INVOICE_TTL)))
        return value if value > 0 else _DEFAULT_INVOICE_TTL
    except ValueError:
        return _DEFAULT_INVOICE_TTL


# ── Invoice persistence (hosting_invoices table — audit item #1) ────────────
def _invoice_to_dict(row: Any) -> dict[str, Any]:
    """Serialize a HostingInvoice row to the public invoice dict."""
    return {
        "invoice_id": row.invoice_id,
        "kind": row.kind,
        "plan_tier": row.plan_tier,
        "user_email": row.user_email,
        "user_id": row.user_id,
        "instance_id": row.instance_id or "",
        "payment_method": row.payment_method,
        "amount_usd": row.amount_usd,
        "amount_atomic": row.amount_atomic,
        "chain": row.chain,
        "pay_to": row.pay_to,
        "asset": row.asset,
        "expires_at": _utc_iso(_aware(row.expires_at)),
        "status": row.status,
        "credited_reference": row.credited_reference or "",
        "payment": dict(row.payment or {}),
        "x402_body": dict(row.x402_body or {}),
        "email_verified": bool(row.email_verified),
        "created_at": _utc_iso(_aware(row.created_at)),
    }


def _save_invoice(record: dict[str, Any]) -> None:
    """Insert or update a hosting invoice row from a record dict."""
    with session_scope() as session:
        row = (
            session.query(_models.HostingInvoice).filter_by(invoice_id=record["invoice_id"]).first()
        )
        if row is None:
            row = _models.HostingInvoice(invoice_id=record["invoice_id"])
            session.add(row)
        row.kind = str(record.get("kind", "signup"))
        row.plan_tier = str(record["plan_tier"])
        user_email = str(record.get("user_email") or "")
        if not user_email and record.get("user_id"):
            urow = session.query(_models.User).filter_by(user_id=str(record["user_id"])).first()
            user_email = str(urow.email) if urow is not None else ""
        row.user_email = user_email
        row.user_id = str(record.get("user_id") or "")
        row.instance_id = str(record.get("instance_id") or "")
        row.payment_method = str(record.get("payment_method", "x402"))
        row.amount_usd = float(record["amount_usd"])
        row.amount_atomic = str(record.get("amount_atomic", "0"))
        row.chain = str(record.get("chain", ""))
        row.pay_to = str(record.get("pay_to", ""))
        row.asset = str(record.get("asset", ""))
        row.status = str(record.get("status", "pending"))
        row.expires_at = _parse_iso(str(record["expires_at"]))
        row.payment = dict(record.get("payment") or {})
        row.x402_body = dict(record.get("x402_body") or {})
        row.verification_code = str(record.get("verification_code") or "")
        row.email_verified = bool(record.get("email_verified", False))


def _load_invoice(invoice_id: str) -> dict[str, Any] | None:
    """Fetch one invoice dict by id (None when unknown)."""
    with session_scope() as session:
        row = session.query(_models.HostingInvoice).filter_by(invoice_id=invoice_id).first()
        return _invoice_to_dict(row) if row is not None else None


def _set_invoice_fields(invoice_id: str, **fields: Any) -> None:
    """Update scalar columns on an invoice row (no-op when unknown)."""
    with session_scope() as session:
        row = session.query(_models.HostingInvoice).filter_by(invoice_id=invoice_id).first()
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)


def reset_hosting_state() -> None:
    """Reset the invoice registry (test/ops compat no-op).

    Invoices now live in the ``hosting_invoices`` table — they survive
    restarts by design, so there is nothing to clear in-process. Tests
    isolate via a per-test SQLite DB (see tests/conftest.py).
    """
    return None
