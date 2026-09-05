"""Pry — shared ASGI middleware helpers: logging setup, headers, route checks.

Split out of the former monolithic middleware.py. Pure helpers with no
request-state; the stateful trusted-proxy block and the middleware class
live in ``middleware.py`` (facade) and ``middleware_http.py`` respectively.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import re
from collections.abc import Mapping
from typing import Any, cast

from starlette.routing import Mount as StarletteMount, Route as StarletteRoute

try:
    from pry.core.logging_config import (
        bind_request_id,
        clear_request_id,
        get_logger as _get_logger,
        setup_logging,
    )

    setup_logging()
    logger = _get_logger(__name__)
except ImportError:  # pragma: no cover
    import logging

    def bind_request_id(_request_id: str) -> None:  # no-op fallback
        return None

    def clear_request_id() -> None:
        return None

    logger = logging.getLogger(__name__)


# ── Security headers (defense-in-depth) ────────────────────────────
# nginx already sets these at the edge; setting them again at the app
# level guarantees a browser/API client behind any proxy still gets
# them (HTML injection / clickjacking / referrer-leak mitigation).
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    # Relax-but-not-open CSP. API responses are JSON; the policy only
    # constrains any rendered HTML. Feasible and safe at the app layer.
    (
        b"content-security-policy",
        b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; img-src 'self' data:; 'sandbox'",
    ),
)


def _get_header(scope: Mapping[str, Any], name: bytes) -> str:
    """Return the first header matching ``name`` (case-insensitive), or ''."""
    for key, value in scope.get("headers", []):
        if key.lower() == name.lower():
            return cast("bytes", value).decode("latin-1")
    return ""


def _route_table_root(app: Any) -> Any:
    """Walk the ASGI middleware chain until a node exposing ``.routes``.

    ``PryHttpMiddleware.app`` points at the NEXT middleware layer (e.g.
    X402Middleware), which has no route table. Checking path existence
    against that layer silently returned False for every request, which
    routed ALL traffic through the unknown-path pass-through — disabling
    rate limiting, request logging, and Prometheus metrics in production.
    """
    node: Any = app
    for _ in range(10):
        if node is None:
            return None
        if hasattr(node, "routes"):
            return node
        node = getattr(node, "app", None)
    return None


def _path_exists(path: str, app) -> bool:
    """Check if a path matches any registered route."""
    root = _route_table_root(app)
    routes = getattr(root, "routes", []) or []

    for route in routes:
        if isinstance(route, StarletteMount):
            if route.path == "" or route.path == "/":
                # Root mount — check all sub-routes
                if route.routes and _path_exists(path, route):
                    return True
                continue
            if path == route.path or path.startswith(route.path.rstrip("/") + "/"):
                if route.routes:
                    sub_path = path[len(route.path) :] if route.path != "/" else path
                    if _path_exists(sub_path, route):
                        return True
                # Mounts without sub-routes catch-all under prefix
                return True
        elif isinstance(route, StarletteRoute):
            route_path = getattr(route, "path", "")
            if route_path:
                # Convert path template to regex
                pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+", route_path) + "$"
                if re.match(pattern, path):
                    return True
    return False
