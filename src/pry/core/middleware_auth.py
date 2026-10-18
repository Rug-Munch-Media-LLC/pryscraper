"""Pry — fail-closed auth policy for the ASGI middleware and config routers.

Shared by ``PryHttpMiddleware`` and the sensitive configuration routers
(routers/proxy.py, routers/config.py) so every egress-mutating endpoint
enforces the same rule as the middleware.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import hmac
import ipaddress
import os
from collections.abc import Mapping, MutableMapping
from typing import Any

from pry.core.jwt_auth import is_jwt, validate_rmi_jwt
from pry.core.middleware_common import _get_header, logger
from pry.core.settings import settings

_AUTH_PUBLIC_PATHS: set[str] = {
    "/health",
    "/healthz",
    "/live",
    "/ready",
    "/readyz",
    "/supported",
    # /metrics is NOT listed: it is gated by metrics_authorized() below.
    # Docs paths stay here because they are only MOUNTED outside prod
    # (app_factory passes docs_url/openapi_url=None in prod), so a prod
    # request for them falls through to the router's 404.
    "/docs",
    "/openapi.json",
    # MCP discovery is public; tools/call is auth-gated inside both the SSE
    # handler (mcp_sse.py) and the Streamable HTTP handler (pry_mcp/app.py).
    "/mcp",
    "/mcp/health",
    "/mcp/sse",
    "/mcp/messages",
    # Well-known discovery endpoints (public for AI agent discovery)
    "/.well-known/agent.json",
    "/.well-known/server.json",
    "/.well-known/x402.json",
    "/.well-known/x402-bazaar.json",
    "/llms.txt",
    # x402 discovery: agents price calls without a key (the 402 is the auth).
    "/v1/x402/pricing",
    "/v1/x402/catalog",
    # Human rail: the payer has no key yet; the payment IS the auth. The
    # portal verifies a signed magic-link token inside the endpoint.
    "/v1/hosting/checkout",
    "/v1/hosting/portal",
    # Email verification link target — the code in the link IS the proof.
    "/v1/hosting/verify",
    # Signup + tx confirm (prefix covers /signup/{invoice_id}/confirm).
    # Keyless requests stay under the IP rate limiter, bounding spam.
    "/v1/hosting/signup",
}

# ── Fail-closed auth policy ──
# Key configured -> valid Bearer (API key or rmi JWT) from EVERY source.
# Key unset -> keyless loopback only, while the dev allowance is on.
# Peer trust: the socket peer is the only identity the connection proves.
# X-Forwarded-For is honoured ONLY when the peer is listed in
# PRY_TRUSTED_PROXIES (comma/space separated IPs or CIDRs; empty = trust
# none). The client is the rightmost hop that is not itself a trusted proxy.
# A malformed chain, or XFF from an untrusted peer, is a spoofing attempt and
# makes the request unauthorised.
_LOOPBACK_OR_TEST_HOSTS: frozenset[str] = frozenset(
    {"127.0.0.1", "::1", "::ffff:127.0.0.1", "testclient"}
)

# ── Ops surfaces ──
# /metrics exposes process internals (counters, tiers, provider health). It is
# not a public endpoint: Prometheus scrapes it over loopback, and a remote
# scraper must present PRY_OPS_TOKEN (X-Ops-Token or Bearer).
# /docs, /redoc and /openapi.json are development aids only. They are 404 in
# prod at the middleware, and stay available in dev/staging.
_OPS_METRICS_PATH = "/metrics"
DOCS_PATHS: frozenset[str] = frozenset(
    {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
)


def docs_enabled() -> bool:
    """True outside prod: interactive docs are a development aid, not a surface."""
    return settings.environment != "prod"


def ops_token_ok(scope: Mapping[str, Any]) -> bool:
    """Constant-time check of PRY_OPS_TOKEN against X-Ops-Token / Bearer."""
    expected = os.getenv("PRY_OPS_TOKEN", "").strip()
    if not expected:
        return False
    supplied = _get_header(scope, b"x-ops-token") or _get_header(scope, b"authorization")
    if supplied.startswith("Bearer "):
        supplied = supplied[7:]
    return bool(supplied) and hmac.compare_digest(
        supplied.encode("utf-8"), expected.encode("utf-8")
    )


class DocsGateMiddleware:
    """Answer 404 for /docs, /redoc and /openapi.json in prod.

    Runs before the auth middleware: an absent surface must not advertise an
    auth wall. Kept as ASGI (not BaseHTTPMiddleware) so it never buffers.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path") in DOCS_PATHS and not docs_enabled():
            body = b'{"detail":"Not Found"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def metrics_authorized(scope: Mapping[str, Any]) -> bool:
    """Authorise a /metrics scrape: dev, loopback peer, or a valid ops token."""
    if settings.environment != "prod":
        return True
    client_ip = resolve_client_ip(scope)
    if client_ip is not None and is_loopback_client(client_ip):
        return True
    return ops_token_ok(scope)


def _parse_trusted_proxy(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """Parse one trusted-proxy entry (IP or CIDR); None when invalid."""
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError:
        logger.warning("pry_trusted_proxy_invalid", extra={"value": value})
        return None


_TRUSTED_PROXY_NETWORKS = tuple(
    net
    for part in os.getenv("PRY_TRUSTED_PROXIES", "").replace(",", " ").split()
    if part.strip() and (net := _parse_trusted_proxy(part.strip())) is not None
)


def _is_trusted_proxy(ip: str) -> bool:
    """Return True when *ip* is in the configured PRY_TRUSTED_PROXIES set."""
    if not ip or ip == "unknown":
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _TRUSTED_PROXY_NETWORKS)


def _xff_hops(xff: str) -> str | None:
    """Resolve the client IP from an X-Forwarded-For chain (None if spoofable)."""
    hops = [hop.strip() for hop in xff.split(",")]
    if not hops or any(not hop for hop in hops):
        return None
    for hop in reversed(hops):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            return None
        if not _is_trusted_proxy(hop):
            return hop
    return hops[0]


def resolve_client_ip(scope: Mapping[str, Any]) -> str | None:
    """Trusted client IP, or None when the forwarding chain is spoofable."""
    client = scope.get("client")
    peer = str(client[0]) if isinstance(client, (list, tuple)) and client else ""
    if not peer or peer == "unknown":
        return None
    xff = _get_header(scope, b"x-forwarded-for")
    if not xff:
        return peer
    if not _is_trusted_proxy(peer):
        return None
    return _xff_hops(xff)


def keyless_loopback_allowed() -> bool:
    """Dev-only loopback allowance: on outside prod, OFF in prod by default."""
    raw = os.getenv("PRY_ALLOW_KEYLESS_LOOPBACK", "").strip().lower()
    if not raw:
        return settings.environment != "prod"
    return raw in ("1", "true", "yes", "on")


def is_loopback_client(ip: str) -> bool:
    """Return True when the peer address is loopback (or the ASGI test client)."""
    if not ip or ip == "unknown":
        return False
    return ip in _LOOPBACK_OR_TEST_HOSTS or ip.startswith(
        ("127.", "::ffff:127.")  # 127.0.0.0/8 loopback range
    )


def _apply_x402_identity(scope: MutableMapping[str, Any]) -> bool:
    """Bind the x402 payer identity (the payment is the credential)."""
    xv = scope["x402_verified"]
    scope["pry_api_key"] = {
        "key_id": f"x402:{xv.get('payment_id') or xv.get('batch_id', '')}",
        "user_id": f"x402:{xv.get('caller', 'unknown')}",
        "name": "x402-paid",
        "scopes": ["scrape", "crawl", "extract", "monitor"],
        "tier": "X402",
    }
    return True


def _authenticate_db_key(token: str) -> Mapping[str, Any] | None:
    """Authenticate a DB-issued key, treating an auth-store outage as no key."""
    try:
        from pry.core.api_keys_service import authenticate as authenticate_db_key

        return authenticate_db_key(token)
    except Exception:  # noqa: BLE001 - auth store outage must not 500
        logger.warning("api_key_store_unavailable")
        return None


def request_authorized(scope: MutableMapping[str, Any]) -> bool:
    """Apply the fail-closed auth policy to an ASGI request scope.

    Key configured -> valid Bearer PRY_API_KEY or rmi JWT required. No key ->
    keyless loopback only. A forwarding header from an untrusted peer is
    rejected rather than ignored.
    """
    api_key = settings.api_key
    # Ops scrape endpoint: loopback or PRY_OPS_TOKEN, never the API key.
    if scope.get("path") == _OPS_METRICS_PATH:
        return metrics_authorized(scope)
    auth = _get_header(scope, b"authorization")
    token = auth[7:] if auth.startswith("Bearer ") else ""

    # x402: the PAYMENT is the credential (settlement verified upstream).
    if scope.get("x402_verified"):
        return _apply_x402_identity(scope)

    # DB-issued keys (pry_...) are valid in both modes and carry identity.
    if token.startswith("pry_"):
        record = _authenticate_db_key(token)
        if record is None:
            return False
        # Bind into the live scope: a local copy is discarded and usage is lost.
        scope["pry_api_key"] = record
        return True

    # Environment billing keys (PRY_BILLING_KEYS): authenticated here, with
    # the tier's quota enforced by BillingEnforcer in middleware_http after
    # auth. These keys have no DB row, so the identity is explicitly marked
    # and carries no ``quota_monthly`` — the user rate limiter must not
    # apply a mismatched default quota on top of the enforcer.
    if token:
        from pry.commerce.billing.enforcer import billing_enforcer

        enforcer = billing_enforcer()
        if enforcer.knows_key(token):
            tier = enforcer.resolve_tier(token)
            scope["pry_api_key"] = {
                "key_id": token,
                "user_id": f"billing:{token[:8]}",
                "name": "billing-key",
                "scopes": ["scrape", "crawl", "extract", "monitor"],
                # The user rate limiter only needs a generous bucket: the
                # paid tier's quota/rpm are enforced by the enforcer.
                "tier": "ENTERPRISE",
                "rate_limit_rpm": tier.rate_limit_rpm,
                "billing_env": True,
            }
            return True

    if api_key:
        # Timing-safe compare: == leaks length/prefix through per-byte timing.
        if hmac.compare_digest(token.encode("utf-8"), api_key.encode("utf-8")):
            # Master key is the bootstrap admin credential (key issuance would
            # otherwise deadlock; the loopback bypass never fires through
            # Docker's published port — the peer is the bridge gateway).
            scope["pry_api_key"] = {
                "key_id": "legacy-master",
                "user_id": "operator",
                "name": "master-key",
                "scopes": ["admin", "scrape", "crawl", "extract", "monitor"],
                "tier": "ENTERPRISE",
            }
            return True
        return bool(is_jwt(token) and validate_rmi_jwt(token))

    # Keyless mode: loopback only, and only while the dev allowance is on.
    if not keyless_loopback_allowed():
        return False
    client_ip = resolve_client_ip(scope)
    return client_ip is not None and is_loopback_client(client_ip)
