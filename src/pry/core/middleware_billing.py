# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Billing-tier enforcement helpers for the HTTP middleware.

Split out of ``middleware_http`` on 2026-10-23: that module is grandfathered at
424 lines by the quality gate, so additions must not live there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pry.core.middleware_auth import _AUTH_PUBLIC_PATHS

if TYPE_CHECKING:
    from collections.abc import Mapping


def billing_allows(scope: Mapping[str, Any]) -> bool:
    """Enforce the billing tier for identities that have no DB limit row.

    DB-issued keys carry ``quota_monthly`` and are already enforced by the
    user rate limiter; charging them here too would double-count. Only
    identities bound from ``PRY_BILLING_KEYS`` (``billing_env``) go through
    the process-wide enforcer.
    """
    from pry.core import middleware as _facade

    record = scope.get("pry_api_key") or {}
    if not record.get("billing_env") or "quota_monthly" in record:
        return True
    return _facade.billing_enforcer().check_request(record.get("key_id"))


def is_public_path(path: str) -> bool:
    """True for an exact public path or a public prefix (e.g. ``/mcp/*``)."""
    return path in _AUTH_PUBLIC_PATHS or any(
        path.startswith(p + "/") for p in _AUTH_PUBLIC_PATHS if p != "/"
    )


def billing_reject(scope: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return ``_reject_rate_limited`` kwargs when billing denies, else None."""
    if billing_allows(scope):
        return None
    record = scope.get("pry_api_key") or {}
    return {
        "api_key": str(record.get("key_id") or ""),
        "stats": {"reason": "billing quota or rate limit exceeded", "retry_after": 60},
        "rate_limit_headers": {},
    }


__all__ = ["billing_reject", "is_public_path"]
