"""Pry — Admin backend for self-hosted monitoring.

SECURITY:
  Admin routes are PREFIXED with PRY_ADMIN_PATH env var. When unset, a random
  32-char hex string is generated on every boot — the endpoint is undiscoverable
  without reading container logs.
  Loopback-only by default (PRY_ADMIN_LOOPBACK_ONLY=true). Set to false to
  expose on all interfaces (PRY_API_KEY auth still required).
  Credentials stored in gopass: `gopass show admin/pryscraper`

Provides profit tracking, system health, Apify earnings, and
Prometheus metrics for Grafana-based dashboards.

Designed for self-hosted Pry instances.

This module is a thin facade: security gate + router live here; endpoints are
implemented in admin_dashboard / admin_users / admin_payments / admin_html and
re-exported below for backwards compatibility (tests import from this module).
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

# ── Admin security: random prefix + loopback-only ──
# Random 32-char hex prevents discovery. Override with PRY_ADMIN_PATH.
_ADMIN_SECRET = os.getenv("PRY_ADMIN_PATH", "") or secrets.token_hex(16)
ADMIN_PREFIX = f"/{_ADMIN_SECRET}"

# Loopback-only: returns 403 for non-local clients even with valid API key.
ADMIN_LOOPBACK_ONLY = os.getenv("PRY_ADMIN_LOOPBACK_ONLY", "true").lower() in ("true", "1", "yes")

# ── File paths for persistent data ──
PRY_DATA_DIR = os.getenv("PRY_DATA_DIR", "/app/data")
ADMIN_DIR = os.path.join(PRY_DATA_DIR, "admin")
os.makedirs(ADMIN_DIR, exist_ok=True)


def _check_admin_access(request: Request) -> None:
    """Enforce loopback-only admin access + admin-role RBAC in remote mode.

    Loopback (default): trusted — no key check (the outer middleware still
    applies when a global key is configured).

    Remote (``PRY_ADMIN_LOOPBACK_ONLY=false``): the presented Bearer key
    must belong to a user with ``role == "ADMIN"`` in the users table —
    ANY valid API key is NOT enough. Fail closed on every failure path.
    """
    client_host = request.client.host if request.client else ""
    is_loopback = client_host in ("127.0.0.1", "::1", "localhost", "0.0.0.0")  # nosec B104 — loopback membership check, not a bind
    if is_loopback and ADMIN_LOOPBACK_ONLY:
        return
    if ADMIN_LOOPBACK_ONLY:
        raise HTTPException(
            status_code=403,
            detail="Admin is loopback-only. Set PRY_ADMIN_LOOPBACK_ONLY=false to expose remotely.",
        )
    # Remote mode: require the caller's key to belong to an ADMIN-role user.
    from pry.core import api_keys_service
    from pry.core.db.session import get_session

    auth = request.headers.get("authorization", "")
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not bearer:
        raise HTTPException(status_code=403, detail="Admin (remote) requires an API key")
    record = api_keys_service.authenticate(bearer)
    if record is None:
        raise HTTPException(status_code=403, detail="Invalid API key for admin access")
    user_id = str(record.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=403, detail="Key is not bound to a user")
    from pry.core.db import models as _db_models

    with get_session() as session:
        urow = session.query(_db_models.User).filter_by(user_id=user_id).first()
    if urow is None or str(urow.role or "").upper() != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Admin access requires a user with the ADMIN role",
        )


router = APIRouter(prefix=ADMIN_PREFIX, tags=["Admin"], dependencies=[Depends(_check_admin_access)])

# ── Endpoint modules (imported AFTER router exists so they can register routes) ──
from pry.api.routers.core.admin_actors import (  # noqa: E402,F401
    admin_actor_detail,
    admin_actors_preview,
)
from pry.api.routers.core.admin_dashboard import (  # noqa: E402,F401
    admin_actors,
    admin_api_usage,
    admin_apify,
    admin_config,
    admin_dashboard,
    admin_health,
    admin_metrics,
    admin_ping,
    admin_profits,
    admin_revenue,
)
from pry.api.routers.core.admin_html import admin_html_dashboard  # noqa: E402,F401
from pry.api.routers.core.admin_payments import (  # noqa: E402,F401
    admin_earnings,
    admin_payments_failed,
    admin_payments_recent,
    admin_treasury,
)
from pry.api.routers.core.admin_shared import (  # noqa: E402,F401
    APIFY_PROFIT,
    CACHE_HIT_RATIO,
    COST_TOTAL,
    PAYMENTS_AMOUNT,
    PAYMENTS_TOTAL,
    REVENUE_TOTAL,
    SCRAPES_ACTIVE,
    SCRAPES_DURATION,
    SCRAPES_TOTAL,
    _compute_profits,
    _earnings_source,
    _fmt_usd,
    _get_apify_profits,
    _get_usage_costs,
    _get_x402_payments,
    _load_jsonl,
    _parse_ts,
    _payment_amount,
)
from pry.api.routers.core.admin_users import (  # noqa: E402,F401
    admin_credit_user,
    admin_revoke_key,
    admin_suspend_user,
    admin_unsuspend_user,
    admin_user_detail,
    admin_users,
)
