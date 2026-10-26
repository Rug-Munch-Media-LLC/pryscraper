"""x402 route classification — fail-closed free/paid gate (audit E41)."""

import logging
import os
from collections.abc import Iterator
from typing import Any

from pry.payments.x402_middleware import config as _pricing_config
from pry.payments.x402_middleware.config import (
    PAID_ENDPOINTS,
)
from pry.payments.x402_middleware.free_paths_a import FREE_PATHS_A
from pry.payments.x402_middleware.free_paths_b import FREE_PATHS_B

logger = logging.getLogger(__name__)

#   2. prefix match in DEFAULT_FREE_PREFIXES        -> free
#   3. under the admin router prefix                -> free (loopback-gated)
#   4. prefix match in PAID_ENDPOINTS with the
#      operation present in X402_PRICING            -> paid
#   5. anything else                                -> unclassified (audit failure)

DEFAULT_FREE_PATHS: frozenset[str] = {*FREE_PATHS_A, *FREE_PATHS_B}

# Prefix-match free routes (wildcard semantics). Covers everything under the
# MCP messages transport without enumerating session ids.
DEFAULT_FREE_PREFIXES: tuple[str, ...] = (
    "/mcp/messages",
    # Read-only site capability catalog: no scrape is performed, so there is
    # nothing to charge. Covers /v1/coverage, /recommend and /{site_id}.
    "/v1/coverage",
)


def _admin_prefix() -> str:
    """Resolve the admin router prefix without a hard import cycle.

    routers.admin derives it from PRY_ADMIN_PATH (or a per-process random
    hex), so the value is only stable within one process — which is exactly
    the lifetime this classification matters for.
    """
    try:
        from pry.api.routers.core.admin import ADMIN_PREFIX

        return ADMIN_PREFIX
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - admin router optional
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_admin_prefix"},
        )
        secret = os.getenv("PRY_ADMIN_PATH", "")
        return f"/{secret}" if secret else "/__admin_unavailable__"


def resolve_operation(path: str) -> str | None:
    """Return the x402 operation for a path, or None if no paid prefix matches.

    More specific PAID_ENDPOINTS entries precede broad ones.
    """
    if path == "/v1/vision":
        return "llm_call"  # image analysis is an LLM call; /v1/vision/models stays free
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
    except ImportError as exc:  # pragma: no cover — resolver unavailable (partial import)
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_caller_key_from_scope"},
        )
        client = scope.get("client")
        if client and isinstance(client, (list, tuple)) and len(client) >= 1 and client[0]:
            return str(client[0])
        return ""
