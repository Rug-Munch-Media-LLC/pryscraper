"""Pry — ASGI middleware for auth, rate limiting, timing, and request logging.

Extracted from api.py during the api-slim refactor so the composition root
(api.py) stays focused on wiring routers and the MCP sub-app.

Contains:

* ``PryHttpMiddleware`` — pure-ASGI auth + rate-limit + timing + logging.
  Implemented as ASGI (instead of @app.middleware('http')) so streaming
  responses such as Server-Sent Events are not buffered/broken by
  BaseHTTPMiddleware.
* ``request_authorized`` / ``is_loopback_client`` — the fail-closed auth
  policy. ``routers/proxy.py`` and ``routers/config.py`` import
  ``request_authorized`` from api.py, which re-exports it from here.
* ``_path_exists`` — route-existence check used to pass unknown paths to the
  404 handler.
* ``_resolve_client_ip`` — trusted-proxy-aware client-IP resolution for the
  rate-limit bucket. ``X-Forwarded-For`` is honored ONLY when the immediate
  socket peer is loopback or listed in ``PRY_TRUSTED_PROXIES``; otherwise the
  socket peer is used, so clients cannot spoof a different rate-limit bucket
  when the service sits behind nginx.

Trusted proxies are configured with the ``PRY_TRUSTED_PROXIES`` environment
variable: a comma/space-separated list of IPs or CIDR blocks
(e.g. ``PRY_TRUSTED_PROXIES="10.0.0.0/8,192.168.1.10"``). Loopback peers are
always trusted, matching the pre-existing testclient/loopback behavior.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import ipaddress
import json
import os
import re
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from starlette.routing import Mount as StarletteMount, Route as StarletteRoute

from deps import ratelimiter
from jwt_auth import is_jwt, validate_rmi_jwt
from observability import REQUEST_COUNT, REQUEST_LATENCY
from settings import settings

try:
    from logging_config import get_logger as _get_logger, setup_logging

    setup_logging()
    logger = _get_logger(__name__)
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


def _path_exists(path: str, app) -> bool:
    """Check if a path matches any registered route."""
    routes = getattr(app, "routes", [])

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


_AUTH_PUBLIC_PATHS: set[str] = {"/health", "/live", "/ready", "/metrics", "/docs", "/openapi.json"}


# ── Fail-closed auth policy ──
# Shared by PryHttpMiddleware and the sensitive configuration routers
# (routers/proxy.py, routers/config.py) so every egress-mutating endpoint
# enforces the same rule as the middleware:
#
#   * PRY_API_KEY configured -> a valid Bearer credential (API key or rmi JWT)
#     is required from EVERY source, loopback included.
#   * PRY_API_KEY unset      -> only loopback clients are allowed; every other
#     source is rejected with 401. This keeps a keyless instance from being
#     exposed to the internet (e.g. when the Docker port mapping is public).
#
# "testclient" is the peer host Starlette's TestClient reports; tests run from
# localhost without a key and must keep passing.
_LOOPBACK_OR_TEST_HOSTS: frozenset[str] = frozenset(
    {"127.0.0.1", "::1", "::ffff:127.0.0.1", "testclient"}
)


def is_loopback_client(ip: str) -> bool:
    """Return True when the peer address is loopback (or the ASGI test client)."""
    if not ip or ip == "unknown":
        return False
    return ip in _LOOPBACK_OR_TEST_HOSTS or ip.startswith(
        ("127.", "::ffff:127.")  # 127.0.0.0/8 loopback range
    )


def request_authorized(scope: Mapping[str, Any]) -> bool:
    """Apply the fail-closed auth policy to an ASGI request scope.

    * key configured -> valid Bearer PRY_API_KEY or rmi JWT required
    * no key         -> loopback client only

    Auth always binds to the socket peer (never X-Forwarded-For): spoofed
    forwarding headers must not let a remote client impersonate loopback.
    """
    api_key = settings.api_key
    if api_key:
        auth = PryHttpMiddleware._get_header(scope, b"authorization")
        if auth.startswith("Bearer "):
            token = auth[7:]
            if token == api_key:
                return True  # Legacy API key — allowed
            if is_jwt(token) and validate_rmi_jwt(token):
                return True  # JWT from rmi-backend — allowed
        return False
    client = scope.get("client")
    return is_loopback_client(client[0] if client else "")


# ── Trusted-proxy aware rate-limit key ───────────────────────────
# nginx (and other reverse proxies) sit on the loopback interface and forward
# the real client in X-Forwarded-For. Bucketing by scope["client"][0] would
# collapse every user behind the proxy into one bucket. We therefore honor
# X-Forwarded-For ONLY when the immediate socket peer is loopback or an
# explicitly configured trusted proxy — otherwise the header is ignored and
# the socket peer is used, which keeps the header unspoofable.
def _parse_trusted_proxy(
    value: str,
) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """Parse a single trusted-proxy entry (IP or CIDR). Returns None if invalid."""
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError:
        logger.warning("pry_trusted_proxy_invalid", extra={"value": value})
        return None


_TRUSTED_PROXY_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
    network
    for part in os.getenv("PRY_TRUSTED_PROXIES", "").replace(",", " ").split()
    if part.strip()
    for network in (_parse_trusted_proxy(part.strip()),)
    if network is not None
)


def _is_trusted_proxy(ip: str) -> bool:
    """Return True when the peer address is in the configured trusted-proxy list."""
    if not ip or ip == "unknown":
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in network for network in _TRUSTED_PROXY_NETWORKS)


def _resolve_client_ip(scope: Mapping[str, Any]) -> str:
    """Resolve the effective client IP used for the rate-limit bucket.

    * Default: the socket peer IP (X-Forwarded-For is spoofable).
    * When the immediate socket peer is loopback or a configured trusted
      proxy, honor X-Forwarded-For and use its leftmost entry — the original
      client per standard proxy-chaining semantics.
    """
    client = scope.get("client")
    peer = client[0] if client else ""
    if not peer or peer == "unknown":
        return "unknown"
    if is_loopback_client(peer) or _is_trusted_proxy(peer):
        xff = PryHttpMiddleware._get_header(scope, b"x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    return peer


# Middleware: auth + rate limit + timing + request logging
class PryHttpMiddleware:
    """Pure-ASGI middleware for auth, rate limiting, timing, and logging.

    Implemented as ASGI (instead of @app.middleware('http')) so streaming
    responses such as Server-Sent Events are not buffered/broken by
    BaseHTTPMiddleware.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    @staticmethod
    def _get_header(scope: Mapping[str, Any], name: bytes) -> str:
        for key, value in scope.get("headers", []):
            if key.lower() == name.lower():
                return cast("bytes", value).decode("latin-1")
        return ""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # CORS preflight: OPTIONS requests carry no credentials and must reach
        # CORSMiddleware without auth/rate-limit gating so browsers can probe
        # cross-origin access before sending the real request.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        start = time.time()
        request_id = self._get_header(scope, b"x-request-id") or uuid.uuid4().hex[:12]
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        ip = _resolve_client_ip(scope)
        response_status = 200

        # Authentication check — fail closed.
        # Runs BEFORE the unknown-path pass-through: a keyless instance must
        # reject every non-loopback source (even for unknown paths) with 401,
        # and a configured key must be presented from every source. The
        # route-existence check below only decides whether an *authorized*
        # request is passed to the router (which 404s unknown paths).
        if path not in _AUTH_PUBLIC_PATHS and not request_authorized(scope):
            body = json.dumps(
                {
                    "type": "/errors/unauthorized",
                    "title": "Unauthorized",
                    "status": 401,
                    "detail": "Invalid or missing API key",
                    "request_id": request_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "code": "unauthorized",
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"x-request-id", request_id.encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # Check if route exists — pass through unknown paths to 404 handler
        _app = getattr(self, "app", None)
        if _app and not _path_exists(path, _app):
            await _app(scope, receive, send)
            return

        allowed, stats = ratelimiter.check(ip)
        if not allowed:
            elapsed = time.time() - start
            logger.warning(
                "rate_limit_blocked",
                extra={
                    "request_id": request_id,
                    "ip": ip,
                    "path": path,
                    "retry_after": stats.get("retry_after", 1),
                },
            )

            body = json.dumps(
                {
                    "type": "/errors/rate_limit_exceeded",
                    "title": "Too Many Requests",
                    "status": 429,
                    "detail": "Rate limit exceeded",
                    "request_id": request_id,
                    "instance": path,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "code": "rate_limit_exceeded",
                    "retry_after": stats.get("retry_after", 1),
                }
            ).encode()
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"x-ratelimit-limit", str(ratelimiter.default_rpm).encode()),
                (b"x-ratelimit-remaining", b"0"),
                (b"x-ratelimit-reset", str(stats.get("retry_after", 1)).encode()),
                (b"x-request-id", request_id.encode()),
            ]
            await send({"type": "http.response.start", "status": 429, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        logger.info(
            "request_start",
            extra={
                "request_id": request_id,
                "method": scope.get("method", "GET"),
                "path": path,
                "ip": ip,
            },
        )

        ratelimit_limit = str(ratelimiter.default_rpm).encode()
        ratelimit_remaining = str(stats.get("remaining", 0)).encode()
        ratelimit_reset = str(stats.get("reset_at", 0)).encode()
        request_id_bytes = request_id.encode()

        async def wrapped_send(message: dict[str, Any]) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message.get("status", 200)
                headers = list(message.get("headers", []))
                headers.append((b"x-ratelimit-limit", ratelimit_limit))
                headers.append((b"x-ratelimit-remaining", ratelimit_remaining))
                headers.append((b"x-ratelimit-reset", ratelimit_reset))
                headers.append((b"x-request-id", request_id_bytes))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped_send)

        elapsed = time.time() - start
        if REQUEST_COUNT and REQUEST_LATENCY:
            REQUEST_COUNT.labels(method=method, endpoint=path, status=str(response_status)).inc()
            REQUEST_LATENCY.labels(endpoint=path).observe(elapsed)
        logger.info(
            "request_end",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "status": response_status,
                "duration": f"{elapsed:.3f}s",
            },
        )
