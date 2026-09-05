"""Pry — subscription activation + status.

Provider-agnostic activation: :func:`activate_subscription` records an
expiry in the in-memory registry (extending from the current expiry on
renewal rollover) with optional JSON persistence, and
:func:`subscription_status` reports the current state including a
best-effort usage snapshot from a fresh
:class:`billing.enforcer.BillingEnforcer`.

NOTE [REVIEW]: the ``usage`` snapshot is per-call construction — it is
best-effort, not the exact counter state of the middleware's long-lived
enforcer instance.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from pry.commerce.billing import subscription as _facade
from pry.commerce.billing.enforcer import BillingEnforcer
from pry.commerce.billing.subscription_invoices import _validate_months
from pry.commerce.billing.subscription_state import (
    _SUBSCRIPTIONS,
    _ensure_loaded,
    _ensure_loaded_locked,
    _lock,
    _save_state_locked,
)
from pry.commerce.billing.subscription_time import _add_months, _parse_iso, _utc_iso
from pry.commerce.billing.tiers import get_tier


# ── Activation + status ─────────────────────────────────────────────────────
def activate_subscription(api_key: str, tier: str, months: int) -> dict[str, Any]:
    """Activate (or renew) a subscription for *api_key*.

    Computes the expiry as ``now + months`` calendar months, extending from
    the CURRENT expiry when the subscription is still active and the tier is
    unchanged (renewal rollover); an expired or downgraded subscription
    restarts from now. Records the subscription in-memory and, when a store
    path is configured, persists it best-effort.

    Returns ``{tier, expires_at}``. Raises ``ValueError`` for unpriced tiers.
    """
    resolved = get_tier(tier)
    if resolved.price_usd_monthly is None:
        raise ValueError(f"tier {resolved.name!r} has no fixed monthly price — cannot activate")
    months = _validate_months(months)

    now = _facade._now()
    with _lock:
        _ensure_loaded_locked()
        previous = _SUBSCRIPTIONS.get(api_key)
        base = now
        if previous is not None:
            try:
                previous_expiry = _parse_iso(str(previous["expires_at"]))
            except ValueError:
                previous_expiry = now
            if previous_expiry > now and str(previous.get("tier", "")) == resolved.name:
                base = previous_expiry
        expires_at = _add_months(base, months)
        record: dict[str, Any] = {
            "api_key": api_key,
            "tier": resolved.name,
            "activated_at": _utc_iso(now),
            "expires_at": _utc_iso(expires_at),
            "months_paid": months,
        }
        _SUBSCRIPTIONS[api_key] = record
        _save_state_locked()
    return {"tier": resolved.name, "expires_at": _utc_iso(expires_at)}


def subscription_status(api_key: str) -> dict[str, Any]:
    """Return the current subscription state for *api_key*.

    Returns ``{tier, active, expires_at, usage}``; unknown keys report the
    FREE tier with no expiry. ``usage`` is a best-effort snapshot from a
    fresh :class:`billing.enforcer.BillingEnforcer` (see module NOTES).
    """
    _ensure_loaded()
    with _lock:
        record = _SUBSCRIPTIONS.get(api_key)
    if record is None:
        return {
            "tier": "free",
            "active": False,
            "expires_at": None,
            "usage": _usage_for(api_key),
        }
    now = _facade._now()
    try:
        expires_at = _parse_iso(str(record["expires_at"]))
    except ValueError:
        expires_at = now
    return {
        "tier": str(record.get("tier", "free")),
        "active": expires_at > now,
        "expires_at": _utc_iso(expires_at),
        "usage": _usage_for(api_key),
    }


def _usage_for(api_key: str) -> dict[str, Any]:
    """Best-effort usage snapshot for *api_key* (never raises)."""
    try:
        stats = BillingEnforcer().usage_stats(api_key)
        return {
            "month_requests": int(stats.get("month_requests", 0)),
            "quota_remaining": stats.get("quota_remaining"),
            "quota_exceeded": bool(stats.get("quota_exceeded", False)),
        }
    except (OSError, ValueError, TypeError):
        return {"month_requests": 0, "quota_remaining": None, "quota_exceeded": False}
