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
from collections.abc import Iterator, Mapping
from typing import Any, cast

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


def _iter_route_templates(route: Any) -> Iterator[tuple[str, bool]]:
    """Yield ``(template, is_prefix)`` for ``route`` and everything under it.

    FastAPI >= 0.141 keeps an ``include_router`` result as a lazy
    ``_IncludedRouter`` wrapper: neither a ``starlette.routing.Route`` nor a
    ``Mount``, with the sub-routes behind ``effective_candidates()`` and the
    include prefix already applied. An isinstance() walk therefore saw none of
    the ~380 API routes and ``_path_exists`` answered False for every real
    path, sending all traffic down the unknown-path pass-through (no
    rate limiting, no billing enforcement, no per-route metrics).
    Duck-typing keeps one implementation across FastAPI/Starlette versions.

    A ``Mount`` is a prefix catch-all (it serves everything under its path),
    so it is yielded with ``is_prefix=True``; plain routes match exactly.
    """
    expand = getattr(route, "effective_candidates", None)
    if expand is not None:
        for candidate in expand():
            yield from _iter_route_templates(candidate)
        return
    path = getattr(route, "path", None)
    children = getattr(route, "routes", None)
    if path:
        # ``routes`` present (even empty) == Mount == prefix catch-all.
        yield path, children is not None
    for child in children or ():
        yield from _iter_route_templates(child)


#: (route_count, compiled) cache slot, attached to the app object so a rebuilt
#: app can never read a stale table and the entry dies with the app.
_ROUTE_CACHE_ATTR = "_pry_route_patterns"


def _template_regex(template: str, is_prefix: bool) -> re.Pattern[str]:
    """Compile a route template (``{param}`` -> one segment) into a matcher."""
    if is_prefix and template == "/":
        return re.compile("^/.*$")
    body = re.sub(r"\{[^}]+\}", "[^/]+", template)
    return re.compile("^" + body + ("(?:/.*)?" if is_prefix else "") + "$")


def _compiled_route_patterns(root: Any) -> tuple[re.Pattern[str], ...]:
    """Compiled path matchers for ``root``'s routes (cached per app object)."""
    routes = getattr(root, "routes", None) or ()
    cached = getattr(root, _ROUTE_CACHE_ATTR, None)
    if cached is not None and cached[0] == len(routes):
        return cast("tuple[re.Pattern[str], ...]", cached[1])
    patterns = tuple(
        _template_regex(template, is_prefix)
        for route in routes
        for template, is_prefix in _iter_route_templates(route)
    )
    setattr(root, _ROUTE_CACHE_ATTR, (len(routes), patterns))
    return patterns


def _path_exists(path: str, app: Any) -> bool:
    """True when the app has a route for ``path`` (any method)."""
    root = _route_table_root(app)
    if root is None:
        return False
    return any(pattern.match(path) for pattern in _compiled_route_patterns(root))
