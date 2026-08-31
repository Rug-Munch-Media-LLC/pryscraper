"""Pry — API-key management router.

Issue / list / revoke API keys and inspect prepaid balances. Loopback-gated
(same policy as the admin surface): key administration is an operator
action; customer self-service comes with the accounts system.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from pry.commerce import billing_service
from pry.core import api_keys_service

router = APIRouter(prefix="/v1/keys", tags=["API Keys"])
logger = logging.getLogger(__name__)


def _require_admin(request: Request) -> None:
    """Loopback operators always pass; remote callers need a key with the
    'admin' scope. Prevents ordinary API keys from managing each other."""
    client = request.scope.get("client")
    if client and client[0] in ("127.0.0.1", "::1", "testclient"):
        return
    record = request.scope.get("pry_api_key") or {}
    if "admin" in (record.get("scopes") or []):
        return
    raise HTTPException(status_code=403, detail="admin scope required")


class IssueKeyRequest(BaseModel):
    name: str = Field(default="", max_length=128)
    tier: str = Field(default="FREE", description="FREE | PRO | ENTERPRISE")
    user_id: str = Field(default=api_keys_service.PRIMARY_USER_ID, max_length=64)
    scopes: list[str] | None = None


class CreditRequest(BaseModel):
    amount_usd: float = Field(gt=0)
    reason: str = Field(default="deposit", description="deposit | grant | refund")
    reference: str = Field(default="", max_length=128)


@router.post("", summary="Issue a new API key (plaintext shown once)")
async def issue_key(request: Request, req: IssueKeyRequest) -> dict[str, Any]:
    _require_admin(request)
    try:
        result = api_keys_service.issue_key(
            user_id=req.user_id,
            name=req.name,
            tier=req.tier,
            scopes=req.scopes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    logger.info("api_key_issued", extra={"key_id": result["key_id"], "tier": req.tier})
    return {"success": True, "data": result}


@router.get("", summary="List API keys")
async def list_keys(request: Request, user_id: str | None = None) -> dict[str, Any]:
    _require_admin(request)
    return {"success": True, "data": api_keys_service.list_keys(user_id)}


@router.delete("/{key_id}", summary="Revoke an API key")
async def revoke_key(request: Request, key_id: str, user_id: str | None = None) -> dict[str, Any]:
    _require_admin(request)
    revoked = api_keys_service.revoke_key(key_id, user_id=user_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="key not found or already revoked")
    logger.info("api_key_revoked", extra={"key_id": key_id})
    return {"success": True, "data": {"key_id": key_id, "revoked": True}}


@router.get("/{key_id}/balance", summary="Prepaid balance for a key's owner")
async def get_balance(request: Request, key_id: str) -> dict[str, Any]:
    _require_admin(request)
    keys = [k for k in api_keys_service.list_keys() if k["key_id"] == key_id]
    if not keys:
        raise HTTPException(status_code=404, detail="key not found")
    return {"success": True, "data": billing_service.get_balance(keys[0]["user_id"])}


@router.post("/{key_id}/credit", summary="Credit a key's owner balance")
async def credit_balance(request: Request, key_id: str, req: CreditRequest) -> dict[str, Any]:
    _require_admin(request)
    keys = [k for k in api_keys_service.list_keys() if k["key_id"] == key_id]
    if not keys:
        raise HTTPException(status_code=404, detail="key not found")
    try:
        result = billing_service.credit(
            keys[0]["user_id"], req.amount_usd, reason=req.reason, reference=key_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True, "data": result}


@router.get("/{key_id}/ledger", summary="Ledger entries for a key's owner")
async def get_ledger(request: Request, key_id: str, limit: int = 50) -> dict[str, Any]:
    _require_admin(request)
    keys = [k for k in api_keys_service.list_keys() if k["key_id"] == key_id]
    if not keys:
        raise HTTPException(status_code=404, detail="key not found")
    return {"success": True, "data": billing_service.ledger(keys[0]["user_id"], limit)}
