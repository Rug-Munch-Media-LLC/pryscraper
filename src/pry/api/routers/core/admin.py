"""Pry — Admin backend for self-hosted monitoring.

SECURITY:
  Admin routes are PREFIXED with PRY_ADMIN_PATH env var. When unset, a random
  32-char hex string is generated on every boot — the endpoint is undiscoverable
  without reading container logs.
  Loopback-only by default (PRY_ADMIN_LOOPBACK_ONLY=true). Set to false to
  expose on all interfaces (PRY_API_KEY auth still required).
  Credentials live in the deployment secrets store, not in the repo.

Provides profit tracking, system health, Apify earnings, and
Prometheus metrics for Grafana-based dashboards.

Designed for self-hosted Pry instances.

This module is a thin facade: the router and its access gate live in the
``admin_router`` leaf (so endpoint modules can import them without a cycle);
data paths live here; endpoints are implemented in admin_dashboard /
admin_users / admin_payments / admin_html and re-exported below for backwards
compatibility (tests import from this module).

NOTE: ``PRY_DATA_DIR`` must stay in THIS module — ``admin_shared._data_dir()``
reads it as a deferred module attribute, and the admin tests monkeypatch it
here to isolate payment-log fixtures.
"""

from __future__ import annotations

import logging
import os

# Re-exported so `from pry.api.routers.core.admin import router` keeps working
# and so the tests' module-attr monkeypatches land on the live gate.
from pry.api.routers.core.admin_router import (  # noqa: F401
    ADMIN_LOOPBACK_ONLY,
    ADMIN_PREFIX,
    _check_admin_access,
    router,
)

logger = logging.getLogger(__name__)

# ── File paths for persistent data ──
PRY_DATA_DIR = os.getenv("PRY_DATA_DIR", "/app/data")
ADMIN_DIR = os.path.join(PRY_DATA_DIR, "admin")
os.makedirs(ADMIN_DIR, exist_ok=True)


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
