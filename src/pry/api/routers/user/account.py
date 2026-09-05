"""Pry — Customer self-service account router (usage & billing).

Endpoints for paying cloud customers to inspect their own usage and
billing state. Every endpoint is authenticated (DB-issued API key via
``scope["pry_api_key"]``, or an rmi JWT); callers with no credentials
get 401. Data is always scoped to the caller's own user_id — no
cross-account access, no admin surface here.

Endpoints (5):
  GET /v1/account/usage            - current-month API usage breakdown
  GET /v1/account/billing-history  - payments made (ledger + x402)
  GET /v1/account/api-keys/stats   - per-API-key usage stats
  GET /v1/account/subscription     - subscription tier/state details
  GET /v1/account/balance          - x402 prepaid balance + runway

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
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func

from pry.core.db import models_auth, models_billing
from pry.core.db.session import get_session
from pry.core.jwt_auth import is_jwt, validate_rmi_jwt

router = APIRouter(prefix="/v1/account", tags=["Account"])
logger = logging.getLogger(__name__)

#: How many days of daily usage history to return.
_USAGE_DAYS = 30


def _request_user_id(request: Request) -> str:
    """Resolve the authenticated caller's user_id (mirrors auth.py's
    ``_request_owner`` pattern).

    Preference order:
      1. ``scope["pry_api_key"]`` — bound by auth middleware for DB-issued
         ``pry_...`` keys and x402-paid requests; carries the canonical
         ``user_id`` used by metering/billing.
      2. An rmi JWT ``sub``/``id`` claim from the Authorization header.

    Raises 401 when the caller has no usable identity.
    """
    record = request.scope.get("pry_api_key") or {}
    user_id = str(record.get("user_id") or "")
    if user_id:
        return user_id
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if token and is_jwt(token):
        claims = validate_rmi_jwt(token)
        sub = str((claims or {}).get("id") or (claims or {}).get("sub") or "")
        if sub:
            return sub
    raise HTTPException(status_code=401, detail="authentication required")


def _month_start(now: datetime) -> datetime:
    """First instant of the current UTC month."""
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _reset_date(now: datetime) -> str:
    """ISO date the monthly quota resets (first day of next month)."""
    year, month = now.year, now.month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return datetime(year, month, 1, tzinfo=UTC).date().isoformat()


@router.get("/usage", summary="Current month's API usage for the authenticated user")
async def get_usage(request: Request) -> dict[str, Any]:
    """Usage breakdown for the current billing month.

    Returns totals, per-endpoint and per-day call counts, plus the
    caller's tier quota state.
    """
    user_id = _request_user_id(request)
    now = datetime.now(UTC).replace(tzinfo=None)
    month_start = _month_start(now)
    window_start = now - timedelta(days=_USAGE_DAYS)

    with get_session() as session:
        base = session.query(models_auth.Usage).filter(models_auth.Usage.user_id == user_id)

        calls_this_month = int(base.filter(models_auth.Usage.created_at >= month_start).count())
        calls_today = int(
            base.filter(models_auth.Usage.created_at >= now.replace(hour=0, minute=0)).count()
        )

        by_endpoint_rows = (
            session.query(models_auth.Usage.operation, func.count(models_auth.Usage.id))
            .filter(
                models_auth.Usage.user_id == user_id,
                models_auth.Usage.created_at >= month_start,
            )
            .group_by(models_auth.Usage.operation)
            .all()
        )
        calls_by_endpoint = {op: int(n) for op, n in by_endpoint_rows}

        day_rows = (
            session.query(func.date(models_auth.Usage.created_at), func.count(models_auth.Usage.id))
            .filter(
                models_auth.Usage.user_id == user_id,
                models_auth.Usage.created_at >= window_start,
            )
            .group_by(func.date(models_auth.Usage.created_at))
            .all()
        )
        counts_by_day = {str(day): int(n) for day, n in day_rows}

        # Tier + quota come from the caller's user row (fallback: key tier).
        tier = str((request.scope.get("pry_api_key") or {}).get("tier") or "FREE").upper()
        user_row = session.query(models_auth.User).filter_by(user_id=user_id).first()
        if user_row is not None and user_row.tier:
            tier = str(user_row.tier).upper()
        quota_limit = int(user_row_quota(user_row)) if user_row is not None else 0

    calls_by_day: list[dict[str, Any]] = []
    for offset in range(_USAGE_DAYS - 1, -1, -1):
        day = (now - timedelta(days=offset)).date().isoformat()
        calls_by_day.append({"date": day, "calls": counts_by_day.get(day, 0)})

    quota_remaining = max(quota_limit - calls_this_month, 0) if quota_limit else None
    return {
        "success": True,
        "data": {
            "calls_this_month": calls_this_month,
            "calls_today": calls_today,
            "calls_by_endpoint": calls_by_endpoint,
            "calls_by_day": calls_by_day,
            "tier": tier,
            "quota_limit": quota_limit if quota_limit else None,
            "quota_remaining": quota_remaining,
            "reset_date": _reset_date(now),
        },
    }


def user_row_quota(user_row: models_auth.User | None) -> int:
    """Monthly quota for the user's tier (0 = unlimited/unknown)."""
    if user_row is None:
        return 0
    tier = str(user_row.tier or "").upper()
    defaults = {"FREE": 10_000, "PRO": 500_000, "ENTERPRISE": 10_000_000}
    return int(defaults.get(tier, 10_000))


@router.get("/billing-history", summary="Billing history (payments made)")
async def get_billing_history(request: Request) -> dict[str, Any]:
    """Payments made by the authenticated user.

    Combines prepaid ledger credits (deposits / packs / grants) with
    x402 on-chain settlements whose payment_id was credited to the
    caller's ledger.
    """
    user_id = _request_user_id(request)
    with get_session() as session:
        ledger_rows = (
            session.query(models_billing.LedgerEntry)
            .filter(
                models_billing.LedgerEntry.user_id == user_id,
                models_billing.LedgerEntry.delta_usd > 0,
            )
            .order_by(models_billing.LedgerEntry.created_at.desc())
            .all()
        )
        settlement_rows = (
            session.query(models_billing.X402SettlementRecord)
            .order_by(models_billing.X402SettlementRecord.created_at.desc())
            .limit(500)
            .all()
        )

    credited_refs = {str(r.reference) for r in ledger_rows if r.reference}
    transactions: list[dict[str, Any]] = []
    total_spent = 0.0

    type_by_reason = {
        "deposit": "pack",
        "grant": "grant",
        "refund": "refund",
    }
    for r in ledger_rows:
        transactions.append(
            {
                "id": f"ledger:{r.id}",
                "date": r.created_at.isoformat() if r.created_at else None,
                "amount_usd": round(float(r.delta_usd), 4),
                "type": type_by_reason.get(str(r.reason), str(r.reason)),
                "chain": "",
                "tx_hash": str(r.reference or ""),
                "status": "completed",
            }
        )
        if str(r.reason) == "usage":
            total_spent += abs(float(r.delta_usd))

    for s in settlement_rows:
        if str(s.payment_id) not in credited_refs:
            continue
        transactions.append(
            {
                "id": f"x402:{s.id}",
                "date": (s.settled_at or s.created_at).isoformat()
                if (s.settled_at or s.created_at)
                else None,
                "amount_usd": round(float(s.amount_usd or 0.0), 4),
                "type": "x402",
                "chain": str(s.network or ""),
                "tx_hash": str(s.tx_hash or ""),
                "status": "settled" if s.success else "failed",
            }
        )
        if s.success:
            total_spent += float(s.amount_usd or 0.0)

    transactions.sort(key=lambda t: str(t["date"] or ""), reverse=True)
    return {
        "success": True,
        "data": {
            "transactions": transactions,
            "total_spent": round(total_spent, 4),
        },
    }


@router.get("/api-keys/stats", summary="Per-API-key usage stats")
async def get_api_key_stats(request: Request) -> dict[str, Any]:
    """Usage stats for each of the caller's API keys (current month)."""
    user_id = _request_user_id(request)
    now = datetime.now(UTC).replace(tzinfo=None)
    month_start = _month_start(now)

    with get_session() as session:
        keys = (
            session.query(models_auth.APIKey)
            .filter(models_auth.APIKey.user_id == user_id)
            .order_by(models_auth.APIKey.created_at.asc())
            .all()
        )
        usage_rows = (
            session.query(models_auth.Usage.api_key_id, func.count(models_auth.Usage.id))
            .filter(
                models_auth.Usage.user_id == user_id,
                models_auth.Usage.created_at >= month_start,
                models_auth.Usage.api_key_id.isnot(None),
            )
            .group_by(models_auth.Usage.api_key_id)
            .all()
        )
    calls_by_key = {str(k): int(n) for k, n in usage_rows}
    return {
        "success": True,
        "data": {
            "keys": [
                {
                    "id": k.key_id,
                    "name": k.name,
                    "calls_this_month": calls_by_key.get(str(k.key_id), 0),
                    "last_used": k.last_used_at.isoformat() if k.last_used_at else None,
                    "rate_limit": int(k.rate_limit_rpm or 0),
                    "is_active": bool(k.is_active),
                }
                for k in keys
            ]
        },
    }


@router.get("/subscription", summary="Subscription details")
async def get_subscription(request: Request) -> dict[str, Any]:
    """Current subscription state for the caller's API key.

    Uses the subscription registry in ``pry.commerce.billing.subscription_state``
    (via ``subscription_status``); unknown keys report the free tier.
    """
    from pry.commerce.billing.subscription_activation import subscription_status
    from pry.commerce.billing.tiers import get_tier

    record = request.scope.get("pry_api_key") or {}
    api_key = str(record.get("key_id") or "")
    if not api_key:
        raise HTTPException(status_code=401, detail="authentication required")

    status = subscription_status(api_key)
    tier = get_tier(str(status.get("tier") or "free"))
    expires_at = status.get("expires_at")

    months_remaining = 0
    current_period_end = None
    if expires_at:
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            now = datetime.now(UTC).replace(tzinfo=expiry.tzinfo)
            current_period_end = expiry.date().isoformat()
            if expiry > now:
                days = (expiry - now).days
                months_remaining = max(days // 30, 0)
        except ValueError:
            logger.warning("subscription_expiry_unparseable", extra={"api_key": api_key})

    return {
        "success": True,
        "data": {
            "tier": tier.name,
            "status": "active" if status.get("active") else "inactive",
            "current_period_end": current_period_end,
            "auto_renew": False,  # prepaid crypto subscriptions do not auto-renew
            "months_remaining": months_remaining,
            "price_per_month": tier.price_usd_monthly,
        },
    }


@router.get("/balance", summary="x402 prepaid balance")
async def get_balance(request: Request) -> dict[str, Any]:
    """Prepaid USD balance with per-chain top-up breakdown and runway.

    ``balance_by_chain`` attributes verified x402 payments to a chain
    family (evm / solana / tron) by network name; ``estimated_days_remaining``
    divides the balance by the caller's average daily usage cost.
    """
    user_id = _request_user_id(request)
    now = datetime.now(UTC).replace(tzinfo=None)
    window_start = now - timedelta(days=_USAGE_DAYS)

    with get_session() as session:
        row = session.query(models_billing.Balance).filter_by(user_id=user_id).first()
        balance_usd = round(float(row.balance_usd), 4) if row is not None else 0.0

        payments = (
            session.query(models_billing.X402PaymentRecord)
            .filter(
                models_billing.X402PaymentRecord.caller_key == user_id,
                models_billing.X402PaymentRecord.verified.is_(True),
            )
            .all()
        )
        last_deposit = (
            session.query(models_billing.LedgerEntry)
            .filter(
                models_billing.LedgerEntry.user_id == user_id,
                models_billing.LedgerEntry.reason == "deposit",
            )
            .order_by(models_billing.LedgerEntry.created_at.desc())
            .first()
        )
        spend_rows = (
            session.query(func.sum(models_auth.Usage.cost_usd))
            .filter(
                models_auth.Usage.user_id == user_id,
                models_auth.Usage.created_at >= window_start,
            )
            .scalar()
        )

    balance_by_chain = {"evm": 0.0, "solana": 0.0, "tron": 0.0}
    for p in payments:
        network = str(p.network or "").lower()
        chain = "solana" if "sol" in network else "tron" if "tron" in network else "evm"
        balance_by_chain[chain] = round(balance_by_chain[chain] + float(p.amount_usd or 0.0), 4)

    total_30d_spend = float(spend_rows or 0.0)
    daily_burn = total_30d_spend / _USAGE_DAYS
    estimated_days = round(balance_usd / daily_burn) if daily_burn > 0 else None

    return {
        "success": True,
        "data": {
            "balance_usd": balance_usd,
            "balance_by_chain": balance_by_chain,
            "last_top_up": last_deposit.created_at.isoformat() if last_deposit else None,
            "estimated_days_remaining": estimated_days,
        },
    }
