"""Pry — fail-closed auth policy for the ASGI middleware and config routers.

Split out of the former monolithic middleware.py. Shared by
``PryHttpMiddleware`` and the sensitive configuration routers
(routers/proxy.py, routers/config.py) so every egress-mutating endpoint
enforces the same rule as the middleware.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import hmac
from collections.abc import MutableMapping
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
    "/metrics",
    "/docs",
    "/openapi.json",
    # MCP sub-app is public (AI agents must discover tools without API key).
    # SECURITY: /mcp/messages and /mcp/sse are public at the middleware layer
    # because the SSE transport requires unauthenticated reachability for
    # discovery.  tools/call (the dangerous operation) is auth-gated INSIDE
    # both mcp_post_message (mcp_sse.py) and the Streamable HTTP handler
    # (pry_mcp/app.py) — an unauthenticated caller gets a JSON-RPC -32001
    # Unauthorized error, not tool execution.
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
    # x402 discovery: agents must be able to price calls without a key
    # (the 402 challenge itself is the auth for paid calls).
    "/v1/x402/pricing",
    "/v1/x402/catalog",
    # Human checkout + customer portal (pre-auth surfaces: the human IS
    # the payer — the checkout page renders the 402 manifest; the portal
    # authenticates via a signed magic-link token carried in the query
    # string, verified inside the endpoint — 401 without a valid token).
    # POST /v1/hosting/portal/request is the rate-limited magic-link
    # request flow (public by design; the rate limit is the protection).
    "/v1/hosting/checkout",
    "/v1/hosting/portal",
    # Email verification link target (humans click it from mail clients —
    # no API key exists yet; the code in the link IS the proof).
    "/v1/hosting/verify",
    # Hosting signup + tx confirm — the FIRST steps of the human rail.
    # A prospective customer has no API key yet (the payment IS the auth,
    # same doctrine as the x402 402-challenge). Prefix match also covers
    # POST /v1/hosting/signup/{invoice_id}/confirm. Keyless requests stay
    # under the IP-based rate limiter, bounding invoice spam.
    "/v1/hosting/signup",
}

# ── Fail-closed auth policy ──
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


def request_authorized(scope: MutableMapping[str, Any]) -> bool:
    """Apply the fail-closed auth policy to an ASGI request scope.

    * key configured -> valid Bearer PRY_API_KEY or rmi JWT required
    * no key         -> loopback client only

    Auth always binds to the socket peer (never X-Forwarded-For): spoofed
    forwarding headers must not let a remote client impersonate loopback.
    """
    api_key = settings.api_key
    auth = _get_header(scope, b"authorization")
    token = auth[7:] if auth.startswith("Bearer ") else ""

    # x402 payment-verified requests: the PAYMENT is the credential. The
    # outer X402Middleware verified on-chain settlement and marked the
    # scope; bind a metering identity so usage/billing still record.
    if scope.get("x402_verified"):
        xv = scope["x402_verified"]
        scope["pry_api_key"] = {
            "key_id": f"x402:{xv.get('payment_id') or xv.get('batch_id', '')}",
            "user_id": f"x402:{xv.get('caller', 'unknown')}",
            "name": "x402-paid",
            "scopes": ["scrape", "crawl", "extract", "monitor"],
            "tier": "X402",
        }
        return True

    # DB-issued keys (pry_...) authenticate against the api_keys table.
    # They are valid in BOTH modes (key configured or keyless loopback) and
    # carry their own identity for rate limiting + metering + billing.
    if token.startswith("pry_"):
        try:
            from pry.core.api_keys_service import authenticate as authenticate_db_key

            record = authenticate_db_key(token)
        except Exception:  # noqa: BLE001 - auth store outage must not 500
            logger.warning("api_key_store_unavailable")
            record = None
        if record is None:
            return False
        # Bind the authenticated key identity INTO the live scope so
        # downstream metering/billing (scope["pry_api_key"]) sees it.
        # ASGI scope is a mutable dict; a local copy here would be discarded
        # and usage would never be recorded (regression from src-layout move).
        scope["pry_api_key"] = record
        return True

    if api_key:
        # Legacy global key, or a JWT issued by rmi-backend.
        # Timing-safe compare (constant-time) for the legacy global key.
        # A plain == comparison leaks the key length/prefix through
        # per-byte timing, letting a remote attacker binary-search the key.
        if hmac.compare_digest(token.encode("utf-8"), api_key.encode("utf-8")):
            # The operator's master key is the bootstrap admin credential:
            # bind a full-scope identity so admin endpoints (/v1/keys
            # issuance) work before any DB key exists. Without this, key
            # issuance deadlocks — remote callers need an admin-scoped key,
            # and the loopback bypass never fires through Docker's published
            # port (ASGI peer is the bridge gateway, e.g. 172.25.0.1).
            scope["pry_api_key"] = {
                "key_id": "legacy-master",
                "user_id": "operator",
                "name": "master-key",
                "scopes": ["admin", "scrape", "crawl", "extract", "monitor"],
                "tier": "ENTERPRISE",
            }
            return True
        return bool(is_jwt(token) and validate_rmi_jwt(token))
    client = scope.get("client")
    first_hop = client[0] if isinstance(client, (list, tuple)) and client else ""
    return is_loopback_client(str(first_hop))
