"""x402 route classification — fail-closed free/paid gate (audit E41)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import os
from collections.abc import Iterator
from typing import Any

from pry.payments.x402_middleware import config as _pricing_config
from pry.payments.x402_middleware.config import (
    PAID_ENDPOINTS,
    X402_PRICING as _X402_PRICING_REF,  # noqa: F401
)

# ── Route classification (fail-closed gate) ──────────────────────────────────
# Every HTTP route MUST be explicitly classified as free or paid. The old
# behavior silently served any route missing from PAID_ENDPOINTS for free,
# which meant a new endpoint (or a pricing-table regression) leaked paid
# capability at $0. The startup audit (audit_route_classification) plus the
# runtime fail-closed branch below close that hole.
#
# Classification rules, in order:
#   1. exact match in DEFAULT_FREE_PATHS            -> free
#   2. prefix match in DEFAULT_FREE_PREFIXES        -> free
#   3. under the admin router prefix                -> free (loopback-gated)
#   4. prefix match in PAID_ENDPOINTS with the
#      operation present in X402_PRICING            -> paid
#   5. anything else                                -> unclassified (audit failure)

DEFAULT_FREE_PATHS: frozenset[str] = frozenset(
    {
        # Infra / observability / docs
        "/health",
        "/healthz",
        "/live",
        "/ready",
        "/readyz",
        "/supported",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
        "/metrics",
        "/version",
        "/dashboard",
        "/v0/stats",
        # MCP sub-app mount + SSE transport
        "/mcp",
        "/mcp/health",
        "/mcp/sse",
        # x402 payment flow itself must be free (chicken-and-egg)
        "/v1/x402/pricing",
        "/v1/x402/catalog",
        "/v1/x402/payment",
        "/v1/x402/verify",
        "/v1/x402/require-payment",
        "/v1/x402/pay",
        "/v1/x402/batch-payment",
        "/v1/x402/batch-verify",
        "/v1/x402/health",
        # Config / capabilities / AI manifests
        "/v1/config",
        "/v1/config/profile/tor",
        "/v1/capabilities",
        "/v1/ai/mcp-config",
        "/v1/ai/gpt-manifest",
        # API-key management (operator surface; auth-gated separately)
        "/v1/keys",
        "/v1/keys/{key_id}",
        # Account surface (auth-gated separately)
        "/v1/account/api-keys/stats",
        "/v1/account/balance",
        "/v1/account/billing-history",
        "/v1/account/subscription",
        "/v1/account/usage",
        "/v1/keys/{key_id}/balance",
        "/v1/keys/{key_id}/credit",
        "/v1/keys/{key_id}/ledger",
        # Billing / bulk scrape-credit packs (control plane — the monetary gate
        # is the x402 PaymentRequired manifest, not the middleware; the balance
        # read + signup are free). Purchase/confirm ARM the gate server-side.
        "/v1/billing/packs",
        "/v1/billing/purchase",
        "/v1/billing/purchase/{invoice_id}/confirm",
        "/v1/billing/subscription/invoice",
        "/v1/billing/subscription/invoice/{invoice_id}/confirm",
        "/v1/billing/signup",
        "/v1/billing/balance",
        # Subscription control-plane (auth-gated separately)
        "/v1/billing/subscription/cancel",
        "/v1/billing/subscription/change-tier",
        "/v1/billing/subscription/renew",
        "/v1/billing/subscription/status",
        # Cloud hosting signup + instance management (control plane — the
        # monetary gate is the 402 payment manifest, not the middleware).
        "/v1/hosting/plans",
        "/v1/hosting/signup",
        "/v1/hosting/signup/{invoice_id}/confirm",
        "/v1/hosting/signup/{invoice_id}/verify",
        "/v1/hosting/instances",
        "/v1/hosting/instances/{instance_id}",
        "/v1/hosting/instances/{instance_id}/renew",
        "/v1/hosting/instances/{instance_id}/cancel",
        # Human checkout + customer portal (control plane — the checkout page
        # renders the 402 manifest for humans; the portal authenticates via a
        # signed magic-link token, and /portal/request is the rate-limited
        # magic-link request flow).
        "/v1/hosting/checkout/{invoice_id}",
        "/v1/hosting/portal",
        "/v1/hosting/portal/request",
        # Email verification link target (humans click from mail clients;
        # pre-auth — the code in the link IS the proof of control).
        "/v1/hosting/verify/{invoice_id}",
        # Job / session management (control plane, not data plane)
        "/v1/job/{job_id}",
        "/v1/jobs",
        "/v1/stream/{job_id}",
        "/v1/session/create",
        "/v1/session/destroy",
        "/v1/session/restore",
        "/v1/session/save",
        "/v1/sessions",
        # Auth connector
        "/v1/auth/captcha",
        "/v1/auth/credentials",
        "/v1/auth/credentials/{credential_id}",
        "/v1/auth/session/health",
        "/v1/auth/sso",
        "/v1/auth/reset-password",
        "/v1/auth/reset-password/confirm",
        # Circuit breaker / diagnostics
        "/v1/breaker/reset",
        "/v1/breaker/status",
        "/v1/diagnostics",
        # Proxy management (control plane)
        "/v1/proxy/clicks",
        "/v1/proxy/configure",
        "/v1/proxy/pool",
        "/v1/proxy/providers",
        "/v1/proxy/recommend",
        "/v1/proxy/referrals",
        "/v1/proxy/referrals/{tag}",
        "/v1/proxy/signup",
        "/v1/proxy/status",
        "/v1/proxy/test",
        # Cookie warming / stealth control plane
        "/v1/cookies/sessions",
        "/v1/cookies/warm",
        "/v1/behavior/simulate",
        "/v1/detect-block",
        # Compliance (legacy free check route — see PAID_ENDPOINTS note)
        "/v1/compliance/check",
        # GDPR / privacy (legal obligation routes stay free)
        "/v1/gdpr/audit",
        "/v1/gdpr/consent",
        "/v1/gdpr/consent/revoke",
        "/v1/gdpr/consent/{user_id}",
        "/v1/gdpr/deletion/execute",
        "/v1/gdpr/deletion/request",
        "/v1/gdpr/retention",
        "/v1/gdpr/retention/apply",
        # Webhooks management
        "/v1/webhooks/dead-letter",
        "/v1/webhooks/test",
        # Alerts / destinations / CRM / commerce sync (outbound integrations)
        "/v1/alert/channels",
        "/v1/alert/send",
        "/v1/destination/send",
        "/v1/destinations",
        "/v1/crm/platforms",
        "/v1/crm/sync",
        "/v1/commerce/platforms",
        "/v1/commerce/search",
        "/v1/commerce/sync",
        "/v1/commerce/{marketplace}/{product_id}",
        # Referral program
        "/v1/referrals/catalog",
        "/v1/referrals/click",
        "/v1/referrals/convert",
        "/v1/referrals/stats",
        # Costing / freshness / quality dashboards
        "/v1/costing/costs",
        "/v1/costing/dashboard",
        "/v1/costing/record",
        "/v1/costing/usage",
        "/v1/freshness/check",
        "/v1/freshness/dashboard",
        "/v1/freshness/frequency",
        "/v1/quality/check",
        "/v1/quality/stats",
        # Pipelines (orchestration control plane)
        "/v1/pipe",
        "/v1/pipeline/hook",
        "/v1/pipeline/hooks",
        "/v1/pipeline/run",
        "/v1/pipelines",
        "/v1/pipelines/run",
        "/v1/pipelines/save",
        "/v1/pipelines/steps",
        "/v1/pipelines/validate",
        "/v1/pipelines/{pipeline_id}",
        # Recording / review / reports
        "/v1/record/clear",
        "/v1/record/export",
        "/v1/record/start",
        "/v1/record/step",
        "/v1/review/submit",
        "/v1/review/{review_id}",
        "/v1/review/{review_id}/approve",
        "/v1/review/{review_id}/reject",
        "/v1/reviews",
        "/v1/report/{report_id}",
        "/v1/reports",
        "/v1/reports/generate",
        # Share
        "/v1/share",
        "/share/{share_id}",
        # Templates registry (execution is paid; listing is free)
        "/v1/templates",
        "/v1/templates/{template_id}",
        # Actors / agency marketplace
        "/v1/actors",
        "/v1/actors/create",
        "/v1/actors/{actor_id}/run",
        "/v1/agency/create",
        "/v1/agency/{agency_id}",
        "/v1/agency/{agency_id}/analytics",
        "/v1/agency/{agency_id}/branding",
        "/v1/agency/{agency_id}/clients",
        "/v1/client/{client_id}/quota",
        # Signup automation
        "/v1/signup",
        # NOTE: the following are currently FREE by explicit decision but are
        # candidates for monetization (expensive scrape/data operations).
        # Moving any of them to PAID_ENDPOINTS requires: an operation entry in
        # X402_PRICING, a pricing review, and client migration notice.
        "/v1/extract",
        "/v1/extract-table",
        "/v1/extract-with-review",
        "/v1/parse",
        "/v1/markdown",
        "/v1/schema",
        "/v1/schema/extract",
        "/v1/schema/extract-html",
        "/v1/suggest",
        "/v1/summarize",
        "/v1/categorize",
        "/v1/compare",
        "/v1/diff",
        "/v1/transform",
        "/v1/enrich",
        "/v1/enrich/tech-stack",
        "/v1/dedup/check",
        "/v1/links",
        "/v1/thumbnail",
        "/v1/export",
        "/v1/run",
        "/v1/watch",
        "/v1/email/gmail",
        "/v1/email/outlook",
        "/v1/email/scrape",
        "/v1/emails",
        "/v1/screenshot",
        "/v1/ocr/extract",
        "/v1/vision",
        "/v1/vision/models",
        "/v1/camoufox/fetch",
        "/v1/tls/impersonate",
        "/v1/tls/rotate",
        "/v1/shadow-dom",
        "/v1/sse/scrape",
        "/v1/ws/scrape",
        "/v1/seo",
        "/v1/seo/analyze",
        "/v1/seo/keywords",
        "/v1/seo/track",
        "/v1/structure/check",
        "/v1/structure/check-template",
        "/v1/structure/monitor",
        "/v1/intel/analyze",
        "/v1/intel/report",
        "/v1/intel/snapshot",
        "/v1/intel/snapshots/{competitor_id}",
        "/v1/social/{platform}/{handle}",
        "/v1/marketplace/amazon/product/{asin}",
        "/v1/marketplace/amazon/search",
        "/v1/marketplace/tiktok/trending",
        "/v1/marketplace/walmart/product/{product_id}",
        "/v1/health/drug/{drug}",
        "/v1/health/insurance/quotes",
        "/v1/health/trials/search",
        "/v1/health/trials/{nct_id}",
        "/v1/reconcile",
        "/v1/reconcile/schemas",
        "/v1/training/classify-license",
        "/v1/training/clean",
        "/v1/training/compliance/{dataset_id}",
        "/v1/training/export",
        # Well-known discovery endpoints (public for AI agent discovery)
        "/.well-known/agent.json",
        "/.well-known/server.json",
        "/.well-known/x402.json",
        "/.well-known/x402-bazaar.json",
        "/llms.txt",
        # Payment analytics dashboard (public for transparency)
        "/v1/analytics/payments",
        "/v1/analytics/api-popularity",
        "/v1/analytics/funnel",
        "/v1/analytics/track",
        "/v1/analytics/visitors",
        # Crypto payment endpoints (free — part of payment flow)
        "/v1/payments/crypto/charge",
        "/v1/payments/crypto/providers",
        "/v1/payments/crypto/status/{charge_id}",
    }
)

# Prefix-match free routes (wildcard semantics). Covers everything under the
# MCP messages transport without enumerating session ids.
DEFAULT_FREE_PREFIXES: tuple[str, ...] = ("/mcp/messages",)


def _admin_prefix() -> str:
    """Resolve the admin router prefix without a hard import cycle.

    routers.admin derives it from PRY_ADMIN_PATH (or a per-process random
    hex), so the value is only stable within one process — which is exactly
    the lifetime this classification matters for.
    """
    try:
        from pry.api.routers.core.admin import ADMIN_PREFIX

        return ADMIN_PREFIX
    except Exception:  # noqa: BLE001  # pragma: no cover - admin router optional
        secret = os.getenv("PRY_ADMIN_PATH", "")
        return f"/{secret}" if secret else "/__admin_unavailable__"


def resolve_operation(path: str) -> str | None:
    """Return the x402 operation for a path, or None if no paid prefix matches.

    First matching prefix wins; PAID_ENDPOINTS is ordered so more specific
    prefixes (e.g. /v1/scrape/methods) precede broad ones (/v1/scrape).
    """
    return next((op for ep, op in PAID_ENDPOINTS.items() if path.startswith(ep)), None)


def classify_path(path: str) -> str:
    """Classify a request path as ``free``, ``paid`` or ``misconfigured``.

    Returns ``"misconfigured"`` when a path matches a paid prefix whose
    operation is absent from X402_PRICING — a deployment bug that used to be
    served free.
    """
    if path in DEFAULT_FREE_PATHS:
        return "free"
    if any(path.startswith(p) for p in DEFAULT_FREE_PREFIXES):
        return "free"
    if path.startswith(_admin_prefix()):
        return "free"
    op = resolve_operation(path)
    if op is not None:
        return "paid" if op in _pricing_config.X402_PRICING else "misconfigured"
    return "misconfigured"


def iter_app_route_paths(app: Any) -> Iterator[str]:
    """Yield concrete route paths from a FastAPI app (or router route list).

    Recent FastAPI versions wrap included routers in lazy ``_IncludedRouter``
    objects that expose no ``.path`` until first request; recurse into their
    original router to enumerate real routes at startup time.
    """
    routes = app.routes if hasattr(app, "routes") else app
    for route in routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            yield route.path
        elif type(route).__name__ == "_IncludedRouter":
            yield from iter_app_route_paths(route.original_router.routes)
        elif hasattr(route, "path"):  # Mount and other path-carrying nodes
            yield route.path


def audit_route_classification(app: Any) -> list[str]:
    """Return every app route path that is not explicitly free or paid.

    Empty list = gate is fully classified. Called from the api lifespan;
    strict mode raises on non-empty results so an unclassified route can
    never reach production silently.
    """
    return sorted({p for p in iter_app_route_paths(app) if classify_path(p) == "misconfigured"})


def _caller_key_from_scope(scope: dict[str, Any]) -> str:
    """Derive a caller binding key from the ASGI connection.

    Uses the trusted-proxy-aware client resolution from
    ``pry.core.middleware`` (socket peer by default; X-Forwarded-For honored
    ONLY when the immediate peer is loopback or a configured trusted proxy —
    behind nginx/cloudflared the peer is the local proxy, so the real client
    IP is required or every internet caller would share one rate-limit
    bucket). Returns "" when no client info is present (e.g. tests / local
    unix sockets); such payments still expire.
    """
    try:
        from pry.core.middleware import _resolve_client_ip

        return str(_resolve_client_ip(scope))
    except ImportError:  # pragma: no cover — resolver unavailable (partial import)
        client = scope.get("client")
        if client and isinstance(client, (list, tuple)) and len(client) >= 1 and client[0]:
            return str(client[0])
        return ""
