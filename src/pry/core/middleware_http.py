"""Pry — pure-ASGI HTTP middleware: auth + rate limiting + timing + logging.

Split out of the former monolithic middleware.py. Implemented as ASGI
(instead of @app.middleware('http')) so streaming responses such as
Server-Sent Events are not buffered/broken by BaseHTTPMiddleware.

Patchable dependencies (``ratelimiter``, ``user_ratelimiter``,
``_path_exists``, ``_resolve_client_ip``) are resolved through the
``pry.core.middleware`` facade at call time so tests that patch the
facade module keep working.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pry.core.audit import audit_event
from pry.core.middleware_auth import _AUTH_PUBLIC_PATHS
from pry.core.middleware_common import (
    _SECURITY_HEADERS,
    _get_header,
    bind_request_id,
    clear_request_id,
    logger,
)
from pry.core.middleware_usage import _record_usage
from pry.core.observability import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    set_span_attributes,
    span,
)
from pry.core.settings import settings
from pry.core.user_ratelimit import TIER_LIMITS


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
        return _get_header(scope, name)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # OpenTelemetry: one span per HTTP request (name "METHOD path").
        # Attributes (status, duration) are attached inside _handle_http via
        # set_span_attributes; tracing is a no-op when OTel is disabled.
        method = scope.get("method", "GET")
        path = scope.get("path", "")
        start = time.time()
        with span(f"{method} {path}", {"http.method": method, "http.target": path}):
            try:
                await self._handle_http(scope, receive, send)
            finally:
                set_span_attributes({"duration_ms": int((time.time() - start) * 1000)})

    async def _handle_http(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        # Resolve patchable dependencies through the facade module so tests
        # patching pry.core.middleware.<name> take effect at call time.
        from pry.core import middleware as _facade

        # CORS preflight: OPTIONS requests carry no credentials and must reach
        # CORSMiddleware without auth/rate-limit gating so browsers can probe
        # cross-origin access before sending the real request.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        start = time.time()
        request_id = self._get_header(scope, b"x-request-id") or uuid.uuid4().hex[:12]
        # Bind request_id into structlog contextvars so EVERY log line emitted
        # during this request (including downstream modules) carries it at the
        # top level of the JSON record. Cleared at every exit path below.
        bind_request_id(request_id)
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        ip = _facade._resolve_client_ip(scope)
        response_status = 200

        # Authentication check — fail closed.
        # Runs BEFORE the unknown-path pass-through: a keyless instance must
        # reject every non-loopback source (even for unknown paths) with 401,
        # and a configured key must be presented from every source. The
        # route-existence check below only decides whether an *authorized*
        # request is passed to the router (which 404s unknown paths).
        # Public paths support exact match or prefix match (e.g. /mcp/*).
        is_public = path in _AUTH_PUBLIC_PATHS or any(
            path.startswith(p + "/") for p in _AUTH_PUBLIC_PATHS if p != "/"
        )
        if not is_public and not _facade.request_authorized(scope):
            await self._reject_unauthorized(scope, send, request_id, path, ip)
            return

        # Check if route exists — pass through unknown paths to 404 handler
        _app = getattr(self, "app", None)
        if _app and not _facade._path_exists(path, _app):
            await self._passthrough_unmatched(scope, receive, send, method=method, start=start)
            return

        allowed, stats, rate_limit_headers, api_key = self._resolve_rate_limit(scope, ip)
        if not allowed:
            await self._reject_rate_limited(
                send,
                request_id=request_id,
                path=path,
                ip=ip,
                api_key=api_key,
                stats=stats,
                rate_limit_headers=rate_limit_headers,
            )
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

        ratelimit_limit = rate_limit_headers["x-ratelimit-limit"].encode()
        ratelimit_remaining = rate_limit_headers["x-ratelimit-remaining"].encode()
        ratelimit_reset = rate_limit_headers["x-ratelimit-reset"].encode()
        request_id_bytes = request_id.encode()

        async def wrapped_send(message: dict[str, Any]) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message.get("status", 200)
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                headers.append((b"x-ratelimit-limit", ratelimit_limit))
                headers.append((b"x-ratelimit-remaining", ratelimit_remaining))
                headers.append((b"x-ratelimit-reset", ratelimit_reset))
                headers.append((b"x-request-id", request_id_bytes))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped_send)

        elapsed = time.time() - start
        set_span_attributes({"http.status_code": response_status})
        # Route TEMPLATE as the label (e.g. /v1/job/{job_id}), never the
        # raw path — raw paths give every unique URL its own Prometheus
        # series and explode cardinality. Unmatched routes (404s from
        # scanners hitting random paths) bucket under a fixed label.
        route = scope.get("route")
        endpoint: str = getattr(route, "path", "") or (
            "unmatched" if response_status == 404 else path
        )
        if REQUEST_COUNT and REQUEST_LATENCY:
            REQUEST_COUNT.labels(
                method=method, endpoint=endpoint, status=str(response_status)
            ).inc()
            REQUEST_LATENCY.labels(endpoint=endpoint).observe(elapsed)
        if scope.get("pry_api_key"):
            _record_usage(
                scope["pry_api_key"],
                operation=endpoint,
                status="success" if response_status < 400 else "error",
                duration_ms=int(elapsed * 1000),
                ip=ip,
            )
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
        clear_request_id()

    # ── Extracted blocks (audit P2) ─────────────────────────────────────────

    async def _reject_unauthorized(
        self,
        scope: dict[str, Any],
        send: Any,
        request_id: str,
        path: str,
        ip: str,
    ) -> None:
        """Audit + send the 401 JSON response for a failed auth check."""
        # Audit (item #21): 401 with a key presented = invalid/revoked key.
        _presented = self._get_header(scope, b"authorization")
        if _presented.startswith("Bearer "):
            audit_event(
                "auth_failure_401",
                actor=_presented[7:][:64],
                path=path,
                ip=ip,
                request_id=request_id,
            )
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
                    *_SECURITY_HEADERS,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
        set_span_attributes({"http.status_code": 401})
        clear_request_id()

    async def _passthrough_unmatched(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
        *,
        method: str,
        start: float,
    ) -> None:
        """Pass unknown paths through to the router (404 handler + metrics)."""
        _app = getattr(self, "app", None)
        # Still count unmatched requests (scanner noise included) under a
        # fixed label — otherwise 404 traffic is invisible to monitoring.
        passthrough_status = 200

        async def passthrough_send(message: dict[str, Any]) -> None:
            nonlocal passthrough_status
            if message["type"] == "http.response.start":
                passthrough_status = message.get("status", 200)
            await send(message)

        await _app(scope, receive, passthrough_send)
        set_span_attributes({"http.status_code": passthrough_status})
        if REQUEST_COUNT and REQUEST_LATENCY:
            REQUEST_COUNT.labels(
                method=method, endpoint="unmatched", status=str(passthrough_status)
            ).inc()
            REQUEST_LATENCY.labels(endpoint="unmatched").observe(time.time() - start)
        clear_request_id()

    def _resolve_rate_limit(
        self, scope: dict[str, Any], ip: str
    ) -> tuple[bool, dict[str, Any], dict[str, str], str | None]:
        """Pick the right limiter (x402 / DB key / legacy IP) and check it.

        Returns ``(allowed, stats, rate_limit_headers, api_key)``.
        """
        from pry.core import middleware as _facade

        # Rate limiting: use user rate limiter if API key present, else IP-based
        auth_header = self._get_header(scope, b"authorization")
        api_key = None
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]

        ratelimiter = _facade.ratelimiter
        user_ratelimiter = _facade.user_ratelimiter

        # x402 payment-verified requests carry NO Authorization header (the
        # on-chain payment IS the credential). request_authorized() bound an
        # identity with tier="X402" into scope["pry_api_key"]. Route them
        # through the user rate limiter with the X402 tier so a paying caller
        # gets the higher paid limit instead of being collapsed into the
        # per-IP FREE bucket (which would throttle paid traffic behind a
        # shared NAT/proxy and undercut what they paid for).
        x402_verified = scope.get("x402_verified")

        if x402_verified:
            key_record = scope.get("pry_api_key") or {}
            xv = x402_verified
            # Bucket per caller (the paying wallet/agent), not per IP — a
            # single payer behind many IPs must share one budget, and many
            # payers behind one IP must not share a budget.
            bucket_id = key_record.get("key_id") or f"x402:{xv.get('caller', 'unknown')}"
            allowed, stats = user_ratelimiter.check(
                api_key_id=bucket_id,
                tier=key_record.get("tier", "X402"),
                rpm=key_record.get("rate_limit_rpm"),
                quota_monthly=key_record.get("quota_monthly"),
                cost_usd=0.0,
            )
            effective_limit = (
                key_record.get("rate_limit_rpm")
                or TIER_LIMITS.get(key_record.get("tier", "X402"), TIER_LIMITS["X402"])["rpm"]
            )
            rate_limit_headers = {
                "x-ratelimit-limit": str(stats.get("limit", effective_limit)),
                "x-ratelimit-remaining": str(stats.get("remaining", 0)),
                "x-ratelimit-reset": str(int(stats.get("quota_reset_at", time.time()))),
                "x-ratelimit-quota-used": str(stats.get("quota_used", 0)),
                "x-ratelimit-quota-limit": str(stats.get("quota_limit", 10000)),
            }
        elif api_key and api_key != settings.api_key:
            # DB-issued key (pry_...) already validated in request_authorized(),
            # which bound the authenticated record into scope["pry_api_key"].
            # Use ITS per-key rate_limit_rpm + quota (set at issue time) so
            # PRY_RATE_LIMIT_RPM / api_keys_service per-key quotas apply, instead
            # of the previous hardcoded "FREE" tier default.
            key_record = scope.get("pry_api_key") or {}
            allowed, stats = user_ratelimiter.check(
                api_key_id=key_record.get("key_id", api_key[:12]),
                tier=key_record.get("tier", "FREE"),
                rpm=key_record.get("rate_limit_rpm"),
                quota_monthly=key_record.get("quota_monthly"),
                cost_usd=0.0,
            )
            effective_limit = key_record.get("rate_limit_rpm") or ratelimiter.default_rpm
            rate_limit_headers = {
                "x-ratelimit-limit": str(stats.get("limit", effective_limit)),
                "x-ratelimit-remaining": str(stats.get("remaining", 0)),
                "x-ratelimit-reset": str(int(stats.get("quota_reset_at", time.time()))),
                "x-ratelimit-quota-used": str(stats.get("quota_used", 0)),
                "x-ratelimit-quota-limit": str(stats.get("quota_limit", 10000)),
            }
        else:
            # Legacy global key or no key — use IP-based rate limiter
            allowed, stats = ratelimiter.check(ip)
            rate_limit_headers = {
                "x-ratelimit-limit": str(ratelimiter.default_rpm),
                "x-ratelimit-remaining": str(stats.get("remaining", 0)),
                "x-ratelimit-reset": str(stats.get("retry_after", 1)),
            }
        return allowed, stats, rate_limit_headers, api_key

    async def _reject_rate_limited(
        self,
        send: Any,
        *,
        request_id: str,
        path: str,
        ip: str,
        api_key: str | None,
        stats: dict[str, Any],
        rate_limit_headers: dict[str, str],
    ) -> None:
        """Audit + send the 429 JSON response for a blocked request."""
        audit_event(
            "rate_limit_429",
            actor=api_key[:64] if api_key else ip,
            path=path,
            ip=ip,
            reason=stats.get("reason", "rate_limited"),
            request_id=request_id,
        )
        logger.warning(
            "rate_limit_blocked",
            extra={
                "request_id": request_id,
                "ip": ip,
                "path": path,
                "retry_after": stats.get("retry_after", 1),
                "reason": stats.get("reason", "rate_limited"),
            },
        )

        body = json.dumps(
            {
                "type": "/errors/rate_limit_exceeded",
                "title": "Too Many Requests",
                "status": 429,
                "detail": stats.get("reason", "Rate limit exceeded"),
                "request_id": request_id,
                "instance": path,
                "timestamp": datetime.now(UTC).isoformat(),
                "code": "rate_limit_exceeded",
                "retry_after": stats.get(
                    "retry_after", stats.get("quota_reset_at", time.time()) - time.time()
                ),
            }
        ).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"x-request-id", request_id.encode()),
            *_SECURITY_HEADERS,
        ]
        # Add rate limit headers
        for k, v in rate_limit_headers.items():
            headers.append((k.encode(), str(v).encode()))
        # RFC 6585 Retry-After: seconds the client should wait before retrying.
        headers.append((b"retry-after", str(int(float(stats.get("retry_after", 1)))).encode()))
        await send({"type": "http.response.start", "status": 429, "headers": headers})
        await send({"type": "http.response.body", "body": body})
        set_span_attributes({"http.status_code": 429})
        clear_request_id()
