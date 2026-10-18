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

from pry.core import middleware_ratelimit
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


def _billing_allows(scope: Mapping[str, Any]) -> bool:
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


def _implicit_bucket_id(api_key: str | None, x402_verified: Any) -> str:
    """Bucket id used when the request carries no bound API-key record.

    Delegates to ``middleware_ratelimit``; kept as a name here for existing
    import sites.
    """
    return middleware_ratelimit.implicit_bucket_id(api_key, x402_verified)


def _is_public_path(path: str) -> bool:
    """True for an exact public path or a public prefix (e.g. ``/mcp/*``)."""
    return path in _AUTH_PUBLIC_PATHS or any(
        path.startswith(p + "/") for p in _AUTH_PUBLIC_PATHS if p != "/"
    )


def _billing_reject(scope: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return ``_reject_rate_limited`` kwargs when billing denies, else None."""
    if _billing_allows(scope):
        return None
    record = scope.get("pry_api_key") or {}
    return {
        "api_key": str(record.get("key_id") or ""),
        "stats": {"reason": "billing quota or rate limit exceeded", "retry_after": 60},
        "rate_limit_headers": {},
    }


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

        # CORS preflight: OPTIONS carries no credentials and must reach
        # CORSMiddleware without auth/rate-limit gating.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        start = time.time()
        request_id = self._get_header(scope, b"x-request-id") or uuid.uuid4().hex[:12]
        # Bind request_id into structlog contextvars for downstream log lines.
        bind_request_id(request_id)
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        ip = _facade._resolve_client_ip(scope)

        # Authentication — fail closed, and BEFORE the unknown-path pass-through.
        if not self._authorized(scope, path):
            await self._reject_unauthorized(scope, send, request_id, path, ip)
            return

        # Unknown paths pass through to the router, which 404s them.
        if self._route_missing(path):
            await self._passthrough_unmatched(scope, receive, send, method=method, start=start)
            return

        # Billing enforcement (post-auth): PRY_BILLING_KEYS tiers were neither
        # authenticated nor enforced before this check.
        billing = _billing_reject(scope)
        if billing is not None:
            await self._reject_rate_limited(
                send, request_id=request_id, path=path, ip=ip, **billing
            )
            return

        allowed, stats, rate_limit_headers, api_key = await self._resolve_rate_limit(scope, ip)
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

        self._log_request_start(scope, request_id, ip)
        wrapped_send, status = self._send_with_headers(send, request_id, rate_limit_headers)
        await self.app(scope, receive, wrapped_send)

        response_status = status[0]
        elapsed = time.time() - start
        set_span_attributes({"http.status_code": response_status})
        endpoint = self._endpoint_label(scope, response_status, path)
        self._record_request_metrics(scope, endpoint, response_status, elapsed)
        self._log_request_end(scope, request_id, response_status, elapsed)
        clear_request_id()

    # ── Extracted blocks (audit P2) ─────────────────────────────────────────

    def _log_request_start(self, scope: dict[str, Any], request_id: str, ip: str) -> None:
        logger.info(
            "request_start",
            extra={
                "request_id": request_id,
                "method": scope.get("method", "GET"),
                "path": scope.get("path", ""),
                "ip": ip,
            },
        )

    def _send_with_headers(
        self, send: Any, request_id: str, rate_limit_headers: dict[str, str]
    ) -> tuple[Any, list[int]]:
        """Wrap ``send`` to add security/rate-limit headers; returns (send, status)."""
        status = [200]

        async def wrapped(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status[0] = message.get("status", 200)
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                for name in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"):
                    headers.append((name.encode(), rate_limit_headers[name].encode()))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        return wrapped, status

    def _endpoint_label(self, scope: dict[str, Any], status: int, path: str) -> str:
        """Route TEMPLATE as the label (never the raw path — cardinality)."""
        route = scope.get("route")
        return getattr(route, "path", "") or ("unmatched" if status == 404 else path)

    def _log_request_end(
        self, scope: dict[str, Any], request_id: str, status: int, elapsed: float
    ) -> None:
        logger.info(
            "request_end",
            extra={
                "request_id": request_id,
                "method": scope.get("method", "GET"),
                "path": scope.get("path", ""),
                "status": status,
                "duration": f"{elapsed:.3f}s",
            },
        )

    def _authorized(self, scope: dict[str, Any], path: str) -> bool:
        """Public path or an authorized request; fail closed otherwise."""
        from pry.core import middleware as _facade

        return _is_public_path(path) or _facade.request_authorized(scope)

    def _route_missing(self, path: str) -> bool:
        """True when no mounted route matches ``path`` (router 404s it)."""
        from pry.core import middleware as _facade

        app = getattr(self, "app", None)
        return bool(app) and not _facade._path_exists(path, app)

    def _record_request_metrics(
        self,
        scope: dict[str, Any],
        endpoint: str,
        status: int,
        elapsed: float,
    ) -> None:
        """Emit Prometheus counters/latency and per-key usage for one request."""
        from pry.core import middleware as _facade

        if REQUEST_COUNT and REQUEST_LATENCY:
            REQUEST_COUNT.labels(
                method=scope.get("method", "GET"), endpoint=endpoint, status=str(status)
            ).inc()
            REQUEST_LATENCY.labels(endpoint=endpoint).observe(elapsed)
        if scope.get("pry_api_key"):
            _record_usage(
                scope["pry_api_key"],
                operation=endpoint,
                status="success" if status < 400 else "error",
                duration_ms=int(elapsed * 1000),
                ip=_facade._resolve_client_ip(scope),
            )

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

    async def _resolve_rate_limit(
        self, scope: dict[str, Any], ip: str
    ) -> tuple[bool, dict[str, Any], dict[str, str], str | None]:
        """Pick the right limiter (x402 / DB key / legacy IP) and check it.

        Returns ``(allowed, stats, rate_limit_headers, api_key)``. The logic
        lives in ``middleware_ratelimit``; this is the middleware's entry to it.
        """
        return await middleware_ratelimit.resolve_rate_limit(scope, ip)

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
        # Add rate limit headers. Quota usage is omitted when the limiter
        # withheld it (quota_unavailable denies without a figure) — emitting
        # the .get() default of 0 there would hand the client a fabricated
        # "this key has used no quota" during a database outage.
        for k, v in rate_limit_headers.items():
            if v is None:
                continue
            headers.append((k.encode(), str(v).encode()))
        # RFC 6585 Retry-After: seconds the client should wait before retrying.
        headers.append((b"retry-after", str(int(float(stats.get("retry_after", 1)))).encode()))
        await send({"type": "http.response.start", "status": 429, "headers": headers})
        await send({"type": "http.response.body", "body": body})
        set_span_attributes({"http.status_code": 429})
        clear_request_id()
