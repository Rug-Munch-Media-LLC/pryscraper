"""First-party (internal) service access for the x402 gate.

Product policy (2026-09-26): external customers stay x402-paid; our own
first-party jobs must not pay ourselves. So a caller presenting
``X-Internal-Token`` with a valid HMAC over the request fingerprint is served
without a payment challenge.

Security posture:
- FAIL CLOSED when ``PRY_INTERNAL_TOKEN`` is unset — an unset token must never
  degrade into "everyone is internal", which would silently zero the revenue
  path for every external agent.
- Constant-time comparison (``hmac.compare_digest``) so a wrong token leaks no
  length/prefix information through timing.
- The HMAC binds method + path + caller identity, so a captured signature is not
  replayable against a different endpoint or client.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

import hashlib
import hmac
import os
from typing import Any

INTERNAL_TOKEN_HEADER = b"x-internal-token"
INTERNAL_SIG_HEADER = b"x-internal-signature"
INTERNAL_SCOPE_KEY = "x402_verified"


def internal_token() -> str:
    """Return the configured internal service token (empty when unset)."""
    return (os.environ.get("PRY_INTERNAL_TOKEN") or "").strip()


def internal_enabled() -> bool:
    """True when the internal free path is configured. Fail-closed when unset."""
    return bool(internal_token())


def _fingerprint(method: str, path: str, caller: str) -> str:
    """Canonicalise the signed fields (shared by signer and verifier)."""
    return f"{method.upper()}\n{path}\n{caller}"


def internal_signature(token: str, method: str, path: str, caller: str) -> str:
    """Build the HMAC an internal caller must present.

    Deliberately dependency-free: callers need no SDK to compute it, and the
    message is stable so a retry can recompute it without server state.
    """
    return hmac.new(
        token.encode(), _fingerprint(method, path, caller).encode(), hashlib.sha256
    ).hexdigest()


def internal_request(scope: dict[str, Any], headers: dict[bytes, bytes]) -> bool:
    """True when the request carries a valid first-party internal credential."""
    token = internal_token()
    if not token:
        return False
    presented = headers.get(INTERNAL_TOKEN_HEADER, b"").decode().strip()
    if not presented or not hmac.compare_digest(presented, token):
        return False
    signature = headers.get(INTERNAL_SIG_HEADER, b"").decode().strip()
    if not signature:
        return False
    expected = internal_signature(
        token,
        str(scope.get("method", "")),
        str(scope.get("path", "")),
        _caller_from_scope(scope),
    )
    return hmac.compare_digest(signature, expected)


def _caller_from_scope(scope: dict[str, Any]) -> str:
    """Derive the caller identity bound into the signature (socket peer)."""
    try:
        from pry.payments.x402_middleware.classification import _caller_key_from_scope

        return _caller_key_from_scope(scope)
    except ImportError:  # pragma: no cover - partial import during startup
        client = scope.get("client")
        if client and isinstance(client, (list, tuple)) and client and client[0]:
            return str(client[0])
        return ""


def mark_internal_verified(scope: dict[str, Any]) -> None:
    """Mark the ASGI scope so the inner auth layer accepts the internal call.

    Same payment-shaped dict the owner path uses — the auth layer reads
    ``payment_id``/``batch_id`` off it, so a plain bool would crash
    ``middleware_auth`` with ``AttributeError``.
    """
    scope[INTERNAL_SCOPE_KEY] = {"payment_id": "internal", "batch_id": "", "internal": True}
