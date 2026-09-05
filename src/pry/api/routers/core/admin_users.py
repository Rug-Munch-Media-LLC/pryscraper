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

from pry.api.routers.core.admin import router

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
    summary="List accounts with balances",
)
async def admin_users(
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """List user accounts joined with their USD balances."""
    from pry.core.db.models import Balance, User
    from pry.core.db.session import get_session

    with get_session() as session:
        rows = (
            session.query(User, Balance)
            .outerjoin(Balance, Balance.user_id == User.user_id)
            .order_by(User.created_at.desc())
            .limit(limit)
            .all()
        )
        users = [
            {
                "user_id": u.user_id,
                "email": u.email,
                "tier": u.tier,
                "role": u.role,
                "is_active": bool(u.is_active),
                "balance_usd": round(float(b.balance_usd), 4) if b else 0.0,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u, b in rows
        ]
    return {"success": True, "count": len(users), "users": users}


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
    return {"success": True, "user_id": user_id, "is_active": False}
