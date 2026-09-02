"""Pry — API-key lifecycle service.

Issues, authenticates, lists and revokes API keys. Keys are stored HASHED
(SHA-256); the plaintext is shown exactly once at issue time. Key format:
``pry_<8-hex-prefix>_<32-hex-secret>`` — the prefix is stored for display
and fast lookup, the hash for verification.

Self-hosted single-operator mode: when no user_id is supplied, keys are
issued to the implicit ``primary`` user (auto-created).

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from pry.core.audit import audit_event
from pry.core.db import models as _models
from pry.core.db.session import get_session

PRIMARY_USER_ID = "primary"
KEY_PREFIX_TAG = "pry"

_TIER_DEFAULTS: dict[str, dict[str, int]] = {
    "FREE": {"rate_limit_rpm": 60, "quota_monthly": 10_000},
    "PRO": {"rate_limit_rpm": 600, "quota_monthly": 500_000},
    "ENTERPRISE": {"rate_limit_rpm": 6_000, "quota_monthly": 10_000_000},
}


def _hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def ensure_user(user_id: str) -> None:
    with get_session() as session:
        exists = session.query(_models.User).filter_by(user_id=user_id).first()
        if exists:
            return
        session.add(
            _models.User(
                user_id=user_id,
                email=f"{user_id}@local",
                password_hash="!",  # noqa: S106 - not a password; OAuth-style sentinel (account is key-auth only)
            )
        )
        session.commit()


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(plaintext, key_hash, key_prefix)`` for a new key."""
    prefix = secrets.token_hex(4)  # 8 hex chars
    secret = secrets.token_hex(16)  # 32 hex chars
    plaintext = f"{KEY_PREFIX_TAG}_{prefix}_{secret}"
    return plaintext, _hash_key(plaintext), f"{KEY_PREFIX_TAG}_{prefix}"


def issue_key(
    *,
    user_id: str = PRIMARY_USER_ID,
    name: str = "",
    tier: str = "FREE",
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    """Issue a new API key. The plaintext is returned ONCE."""
    tier = tier.upper()
    if tier not in _TIER_DEFAULTS:
        raise ValueError(f"unknown tier '{tier}' (expected FREE/PRO/ENTERPRISE)")
    ensure_user(user_id)
    plaintext, key_hash, key_prefix = generate_api_key()
    defaults = _TIER_DEFAULTS[tier]
    record = {
        "key_id": f"key_{secrets.token_hex(8)}",
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "user_id": user_id,
        "name": name or f"{tier} key",
        "scopes": scopes if scopes is not None else ["scrape", "crawl", "x402"],
        "rate_limit_rpm": defaults["rate_limit_rpm"],
        "quota_monthly": defaults["quota_monthly"],
        "expires_at": expires_at,
    }
    with get_session() as session:
        session.add(_models.APIKey(**record))
        session.commit()
    return {"plaintext": plaintext, **record}


def authenticate(bearer: str) -> dict[str, Any] | None:
    """Resolve a Bearer credential to an active API-key record.

    Returns ``None`` for non-pry tokens, unknown hashes, revoked and
    expired keys. Updates ``last_used_at`` on success.
    """
    bearer = bearer.strip()
    if not bearer.startswith(f"{KEY_PREFIX_TAG}_"):
        return None
    key_hash = _hash_key(bearer)
    with get_session() as session:
        row = session.query(_models.APIKey).filter_by(key_hash=key_hash, is_active=True).first()
        if row is None:
            return None
        if row.expires_at is not None:
            expiry = row.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if datetime.now(UTC) >= expiry:
                return None
        payload = {
            "key_id": row.key_id,
            "user_id": row.user_id,
            "name": row.name,
            "scopes": list(row.scopes or []),
            "rate_limit_rpm": int(row.rate_limit_rpm or 60),
            "quota_monthly": int(row.quota_monthly or 10_000),
        }
        row.last_used_at = datetime.now(UTC)
        session.commit()
        return payload


def revoke_key(key_id: str, *, user_id: str | None = None) -> bool:
    """Revoke a key. Scoped to user_id when provided. True if revoked."""
    with get_session() as session:
        query = session.query(_models.APIKey).filter_by(key_id=key_id)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        row = query.first()
        if row is None or not row.is_active:
            return False
        row.is_active = False
        session.commit()
        audit_event(
            "api_key_revoked",
            actor=user_id or "system",
            path=f"api_keys/{key_id}",
            key_id=key_id,
            owner_user_id=row.user_id,
        )
        return True


def list_keys(user_id: str | None = None) -> list[dict[str, Any]]:
    """List keys (never returns hashes/plaintexts)."""
    with get_session() as session:
        query = session.query(_models.APIKey)
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        rows = query.order_by(_models.APIKey.created_at.desc()).all()
        return [
            {
                "key_id": r.key_id,
                "key_prefix": r.key_prefix,
                "user_id": r.user_id,
                "name": r.name,
                "scopes": list(r.scopes or []),
                "rate_limit_rpm": int(r.rate_limit_rpm or 0),
                "quota_monthly": int(r.quota_monthly or 0),
                "is_active": bool(r.is_active),
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
