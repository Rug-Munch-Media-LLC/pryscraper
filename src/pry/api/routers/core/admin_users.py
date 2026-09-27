"""Admin user management and API-key revocation endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import (
    APIRouter,  # noqa: F401 - re-exported for module consumers
    Body,
    HTTPException,
    Query,
)

from pry.api.routers.core.admin_router import router

logger = logging.getLogger(__name__)


@router.delete(
    "/v1/admin/keys/{key_id}",
    summary="Revoke an API key (fail-closed: authenticate() rejects it immediately)",
)
async def admin_revoke_key(key_id: str) -> dict[str, Any]:
    """Operator revocation path. Keys are validated per-request against the
    DB (no in-memory key cache), so revocation takes effect on the next call."""
    from pry.core import api_keys_service

    revoked = api_keys_service.revoke_key(key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail=f"key not found: {key_id}")
    logger.info("admin_api_key_revoked", extra={"key_id": key_id})
    return {"success": True, "revoked": True, "key_id": key_id}


@router.get(
    "/v1/admin/users",
    summary="List accounts with balances, usage, and subscription status",
)
async def admin_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Paginated user list with tier, activity, monthly API calls, and
    subscription status for the cloud admin panel."""
    from datetime import UTC, datetime

    from sqlalchemy import func as sa_func

    from pry.core.db.models import APIKey, Balance, HostedInstance, Usage, User
    from pry.core.db.session import get_session

    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        total = session.query(User).count()
        rows = (
            session.query(User, Balance)
            .outerjoin(Balance, Balance.user_id == User.user_id)
            .order_by(User.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        page_user_ids = [u.user_id for u, _ in rows]
        calls_by_user: dict[str, int] = {}
        last_used_by_user: dict[str, Any] = {}
        sub_status_by_user: dict[str, str] = {}
        if page_user_ids:
            usage_rows = (
                session.query(Usage.user_id, sa_func.count())
                .filter(
                    Usage.user_id.in_(page_user_ids),
                    Usage.created_at >= month_start,
                )
                .group_by(Usage.user_id)
                .all()
            )
            calls_by_user = dict(usage_rows)
            key_rows = (
                session.query(APIKey.user_id, APIKey.last_used_at)
                .filter(APIKey.user_id.in_(page_user_ids), APIKey.last_used_at.isnot(None))
                .all()
            )
            for uid, last_used in key_rows:
                prev = last_used_by_user.get(uid)
                if prev is None or (last_used and last_used > prev):
                    last_used_by_user[uid] = last_used
            instance_rows = (
                session.query(HostedInstance.user_id, HostedInstance.status)
                .filter(HostedInstance.user_id.in_(page_user_ids))
                .order_by(HostedInstance.created_at.desc())
                .all()
            )
            for uid, status in instance_rows:
                sub_status_by_user.setdefault(uid, str(status or "none"))

        users = [
            {
                "id": u.user_id,
                "user_id": u.user_id,
                "email": u.email,
                "tier": u.tier,
                "role": u.role,
                "is_active": bool(u.is_active),
                "balance_usd": round(float(b.balance_usd), 4) if b else 0.0,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_active": (
                    max(
                        filter(None, [u.last_login_at, last_used_by_user.get(u.user_id)]),
                        default=None,
                    ).isoformat()
                    if (u.last_login_at or last_used_by_user.get(u.user_id))
                    else None
                ),
                "api_calls_this_month": calls_by_user.get(u.user_id, 0),
                "subscription_status": sub_status_by_user.get(u.user_id, "none"),
            }
            for u, b in rows
        ]
    return {"success": True, "users": users, "total": total, "page": page, "per_page": per_page}


@router.get(
    "/v1/admin/users/{user_id}",
    summary="User detail: profile, recent API calls, subscription + billing history",
)
async def admin_user_detail(user_id: str) -> dict[str, Any]:
    """Full detail view for one user for the admin panel."""
    from pry.core.db.models import APIKey, Balance, HostedInstance, LedgerEntry, Usage, User
    from pry.core.db.session import get_session

    with get_session() as session:
        user = session.query(User).filter_by(user_id=user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
        balance = session.query(Balance).filter_by(user_id=user_id).first()
        recent_calls = (
            session.query(Usage)
            .filter_by(user_id=user_id)
            .order_by(Usage.created_at.desc())
            .limit(25)
            .all()
        )
        instances = (
            session.query(HostedInstance)
            .filter_by(user_id=user_id)
            .order_by(HostedInstance.created_at.desc())
            .all()
        )
        ledger = (
            session.query(LedgerEntry)
            .filter_by(user_id=user_id)
            .order_by(LedgerEntry.created_at.desc())
            .limit(50)
            .all()
        )
        keys = session.query(APIKey).filter_by(user_id=user_id).all()

        def _iso(dt: Any) -> str | None:
            return dt.isoformat() if dt else None

        return {
            "success": True,
            "user": {
                "id": user.user_id,
                "email": user.email,
                "tier": user.tier,
                "role": user.role,
                "is_active": bool(user.is_active),
                "is_verified": bool(user.is_verified),
                "wallet": user.wallet,
                "created_at": _iso(user.created_at),
                "last_login_at": _iso(user.last_login_at),
                "balance_usd": round(float(balance.balance_usd), 4) if balance else 0.0,
            },
            "api_keys": [
                {
                    "key_id": k.key_id,
                    "name": k.name,
                    "key_prefix": k.key_prefix,
                    "is_active": bool(k.is_active),
                    "last_used_at": _iso(k.last_used_at),
                    "quota_monthly": k.quota_monthly,
                }
                for k in keys
            ],
            "recent_api_calls": [
                {
                    "operation": c.operation,
                    "endpoint": c.endpoint,
                    "status": c.status,
                    "duration_ms": c.duration_ms,
                    "cost_usd": round(float(c.cost_usd), 6),
                    "created_at": _iso(c.created_at),
                }
                for c in recent_calls
            ],
            "subscription_history": [
                {
                    "instance_id": i.instance_id,
                    "plan_tier": i.plan_tier,
                    "status": i.status,
                    "created_at": _iso(i.created_at),
                    "expires_at": _iso(i.expires_at),
                }
                for i in instances
            ],
            "billing_history": [
                {
                    "delta_usd": round(float(e.delta_usd), 6),
                    "reason": e.reason,
                    "reference": e.reference,
                    "balance_after": round(float(e.balance_after), 6),
                    "created_at": _iso(e.created_at),
                }
                for e in ledger
            ],
        }


@router.post(
    "/v1/admin/users/{user_id}/credit",
    summary="Grant balance to a user",
)
async def admin_credit_user(
    user_id: str,
    body: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    """Credit a user's balance via billing_service.credit."""
    from pry.commerce import billing_service

    try:
        amount = float(body.get("amount_usd", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="amount_usd must be a number") from None
    reason = str(body.get("reason", "grant"))
    if amount <= 0:
        raise HTTPException(status_code=422, detail="amount_usd must be positive")
    try:
        result = billing_service.credit(
            user_id, amount, reason=reason, reference=str(body.get("reference", ""))
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"success": True, "user_id": user_id, "result": result}


@router.post(
    "/v1/admin/users/{user_id}/suspend",
    summary="Disable a user account",
)
async def admin_suspend_user(user_id: str) -> dict[str, Any]:
    """Set is_active=False on the user account."""
    from pry.core.db.models import User
    from pry.core.db.session import get_session

    with get_session() as session:
        user = session.query(User).filter_by(user_id=user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
        user.is_active = False  # type: ignore[assignment]
        session.commit()
    logger.info("admin_user_suspended", extra={"user_id": user_id})
    return {"success": True, "user_id": user_id, "is_active": False}


@router.post(
    "/v1/admin/users/{user_id}/unsuspend",
    summary="Re-enable a suspended user account",
)
async def admin_unsuspend_user(user_id: str) -> dict[str, Any]:
    """Set is_active=True on the user account (restores API access)."""
    from pry.core.db.models import User
    from pry.core.db.session import get_session

    with get_session() as session:
        user = session.query(User).filter_by(user_id=user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
        user.is_active = True  # type: ignore[assignment]
        session.commit()
    logger.info("admin_user_unsuspended", extra={"user_id": user_id})
    return {"success": True, "user_id": user_id, "is_active": True}
