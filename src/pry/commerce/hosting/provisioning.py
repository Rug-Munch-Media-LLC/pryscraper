# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hosted-instance provisioning + lifecycle management.

Covers account resolution (deterministic per-email user ids), instance
creation with API-key minting, expiry extension (renewal rollover), and the
get / list / suspend / cancel lifecycle operations.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from pry.commerce.hosting.errors import InstanceNotFound
from pry.commerce.hosting.persistence import _add_months, _aware, _now, _parse_iso, _utc_iso
from pry.commerce.hosting.plans import get_plan
from pry.core.db import models as _models
from pry.core.db.session import get_session

logger = logging.getLogger("pry.commerce.hosting")


# ── Accounts ────────────────────────────────────────────────────────────────
def _ensure_user_by_email(user_email: str) -> str:
    """Find or create a :class:`User` row for *user_email*; return its user_id.

    Deterministic id (``host_<sha256(email)[:12]>``) so repeat signups with
    the same email resolve to the same account.
    """
    email = user_email.strip().lower()
    if not email or "@" not in email:
        raise ValueError("a valid user_email is required")
    user_id = f"host_{hashlib.sha256(email.encode()).hexdigest()[:12]}"
    with get_session() as session:
        row = session.query(_models.User).filter_by(email=email).first()
        if row is not None:
            return str(row.user_id)
        session.add(
            _models.User(
                user_id=user_id,
                email=email,
                password_hash="!",  # noqa: S106 - key-auth-only sentinel (see api_keys_service)
            )
        )
        session.commit()
        return user_id


# ── Provisioning ────────────────────────────────────────────────────────────
def _provision_instance(user_id: str, plan_tier: str) -> tuple[dict[str, Any], str]:
    """Create a HostedInstance row + mint an API key. Returns (instance, plaintext)."""
    from pry.core.api_keys_service import (
        issue_key,
    )

    plan = get_plan(plan_tier)
    tier_map = {"pro": "PRO", "team": "PRO", "enterprise": "ENTERPRISE"}
    issued = issue_key(
        user_id=user_id,
        name=f"hosted-{plan.tier}",
        tier=tier_map.get(plan.tier, "PRO"),
        scopes=["scrape", "crawl", "x402"],
    )
    instance_id = f"inst_{uuid.uuid4().hex[:12]}"
    now = _now()
    resource_limit = {
        "max_concurrent_scrapes": plan.max_concurrent_scrapes,
        "max_pages_month": plan.max_pages_month,
        "storage_gb": plan.storage_gb,
    }
    with get_session() as session:
        row = _models.HostedInstance(
            instance_id=instance_id,
            user_id=user_id,
            plan_tier=plan.tier,
            status="active",
            api_key=issued["key_id"],  # reference only — never the plaintext
            created_at=now,
            expires_at=_add_months(now, 1),
            region="us-east",
            resource_limit=resource_limit,
        )
        session.add(row)
        session.commit()
    logger.info(
        "hosted_instance_provisioned",
        extra={"instance_id": instance_id, "user_id": user_id, "plan_tier": plan.tier},
    )
    return _instance_payload(instance_id), issued["plaintext"]


def _extend_instance(instance_id: str, *, months: int = 1) -> dict[str, Any]:
    """Extend a hosted instance's expiry by *months* (renewal rollover)."""
    with get_session() as session:
        row = session.query(_models.HostedInstance).filter_by(instance_id=instance_id).first()
        if row is None:
            raise InstanceNotFound(f"unknown hosted instance {instance_id!r}")
        base = row.expires_at if _aware(row.expires_at) > _now() else _now()
        row.expires_at = _add_months(base, months)
        if row.status == "suspended":
            row.status = "active"  # renewal clears a non-payment suspension
        session.commit()
    return _instance_payload(instance_id)


def _instance_payload(instance_id: str) -> dict[str, Any]:
    """Serialize a HostedInstance row (never exposes key material)."""
    with get_session() as session:
        row = session.query(_models.HostedInstance).filter_by(instance_id=instance_id).first()
        if row is None:
            raise InstanceNotFound(f"unknown hosted instance {instance_id!r}")
        return {
            "instance_id": row.instance_id,
            "user_id": row.user_id,
            "plan_tier": row.plan_tier,
            "status": row.status,
            "api_key_id": row.api_key,
            "created_at": _utc_iso(_aware(row.created_at)),
            "expires_at": _utc_iso(_aware(row.expires_at)),
            "region": row.region,
            "resource_limit": dict(row.resource_limit or {}),
        }


# ── Instance management ─────────────────────────────────────────────────────
def get_instance(instance_id: str) -> dict[str, Any]:
    """Return instance details + status. Raises :class:`InstanceNotFound`."""
    payload = _instance_payload(instance_id)
    payload["active"] = (
        payload["status"] == "active" and _aware(_parse_iso(payload["expires_at"])) > _now()
    )
    return payload


def suspend_instance(instance_id: str) -> dict[str, Any]:
    """Suspend an instance (non-payment). Idempotent."""
    with get_session() as session:
        row = session.query(_models.HostedInstance).filter_by(instance_id=instance_id).first()
        if row is None:
            raise InstanceNotFound(f"unknown hosted instance {instance_id!r}")
        row.status = "suspended"
        session.commit()
    logger.info("hosted_instance_suspended", extra={"instance_id": instance_id})
    return _instance_payload(instance_id)


def cancel_instance(instance_id: str) -> dict[str, Any]:
    """Cancel a hosted subscription. The instance stops renewing."""
    with get_session() as session:
        row = session.query(_models.HostedInstance).filter_by(instance_id=instance_id).first()
        if row is None:
            raise InstanceNotFound(f"unknown hosted instance {instance_id!r}")
        row.status = "cancelled"
        session.commit()
    logger.info("hosted_instance_cancelled", extra={"instance_id": instance_id})
    return _instance_payload(instance_id)


def list_instances(user_id: str) -> list[dict[str, Any]]:
    """All hosted instances for *user_id* (newest first)."""
    with get_session() as session:
        rows = (
            session.query(_models.HostedInstance)
            .filter_by(user_id=user_id)
            .order_by(_models.HostedInstance.created_at.desc())
            .all()
        )
        return [
            {
                "instance_id": r.instance_id,
                "plan_tier": r.plan_tier,
                "status": r.status,
                "created_at": _utc_iso(_aware(r.created_at)),
                "expires_at": _utc_iso(_aware(r.expires_at)),
                "region": r.region,
            }
            for r in rows
        ]
