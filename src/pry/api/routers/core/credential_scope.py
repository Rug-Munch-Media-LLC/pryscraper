"""Credential-vault owner derivation — one identity per caller, never a pool.

``auth._request_owner`` used to return ``""`` for any request without an
``Authorization`` header. Every unauthenticated caller therefore shared one
namespace in the credential vault, so caller A could list, read and delete
caller B's credentials (OWASP A01 Broken Access Control / CWE-639 IDOR).

This module holds the derivation so the router stays a thin HTTP shell and
the security policy lives in one testable place.

Policy:

* Authenticated callers keep their existing stable owners: middleware-stashed
  identity, then a JWT ``id`` claim, then a one-way hash of the API key.
* An unauthenticated caller gets an IP-derived owner, so its namespace is
  its own. The IP comes from the shared trusted-proxy-aware resolver, which
  only honors ``X-Forwarded-For`` behind a configured proxy — the client
  cannot spoof its way into another caller's namespace.
* The shared legacy owner ``""`` (rows written before owner-scoping existed)
  is never returned on the default path. Reaching it needs the explicit
  ``PRY_ALLOW_LEGACY_SHARED_CREDENTIALS`` opt-in AND an unresolvable client
  IP, and it is surfaced as a named constant so every reference is greppable.

Trade-off, stated plainly: a caller behind rotating IPs (mobile, CGNAT) gets
a different owner per address and loses sight of earlier credentials. That
is the accepted cost of not handing the whole internet one shared namespace.
Operators who cannot accept it set ``PRY_REQUIRE_AUTH_CREDENTIALS=1`` and
anonymous callers get a hard refusal instead.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING

from pry.core.errors import InvalidRequestError
from pry.core.jwt_auth import is_jwt, validate_rmi_jwt
from pry.core.middleware import _resolve_client_ip

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import Request

#: Owner of rows written before owner-scoping existed. Shared by every
#: pre-scoping caller, which is exactly why it must never be a default.
LEGACY_SHARED_OWNER = ""

#: Opt-in exposing the shared legacy namespace to a caller whose client IP
#: cannot be resolved. Exists for a deliberate operator migration of legacy
#: rows onto a real owner — not as a way to keep anonymous vault access.
ALLOW_LEGACY_SHARED_OWNER = "PRY_ALLOW_LEGACY_SHARED_CREDENTIALS"

#: Set to "1" to refuse anonymous callers of the credential vault outright.
REQUIRE_AUTH_FOR_CREDENTIALS = "PRY_REQUIRE_AUTH_CREDENTIALS"

_TRUTHY = ("1", "true", "yes")


def _flag(name: str) -> bool:
    """Return whether an opt-in env flag is enabled."""
    return os.getenv(name, "").strip().lower() in _TRUTHY


def _stashed_identity(request: Request) -> str:
    """Return the identity stashed on request.state by auth middleware."""
    state = getattr(request, "state", None)
    if state is None:
        return ""
    return str(getattr(state, "identity", None) or getattr(state, "user_id", None) or "")


def _bearer_token(request: Request) -> str:
    """Return the bearer token from the Authorization header, or ""."""
    auth = request.headers.get("authorization", "") if request.headers else ""
    if not auth.lower().startswith("bearer "):
        return ""
    return auth[7:].strip()


def _token_owner(token: str) -> str:
    """Map a validated bearer credential to a stable owner id."""
    if is_jwt(token):
        claims = validate_rmi_jwt(token)
        if claims and claims.get("id"):
            return f"jwt:{claims['id']}"
    return f"key:{hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]}"


def _ip_owner(request: Request) -> str:
    """Derive a stable, IP-scoped owner id for an unauthenticated caller.

    SHA-256 over the client IP keeps the raw address out of the on-disk vault
    while remaining stable for that caller across requests, so an anonymous
    user can still list and delete their own credentials.

    Raises:
        InvalidRequestError: when the client IP cannot be resolved and the
            legacy opt-in is not set. Returning the shared legacy owner here
            unconditionally would recreate the vulnerability this replaced.
    """
    client_ip = _resolve_client_ip(request.scope)
    if not client_ip or client_ip == "unknown":
        if _flag(ALLOW_LEGACY_SHARED_OWNER):
            return LEGACY_SHARED_OWNER
        raise InvalidRequestError("Client IP unavailable; cannot scope credentials")
    return f"anon:{hashlib.sha256(client_ip.encode('utf-8')).hexdigest()[:16]}"


def request_owner(request: Request) -> str:
    """Derive a stable per-caller owner id for credential-vault scoping.

    Preference order:
      1. Identity stashed on ``request.state`` by auth middleware.
      2. A validated ``Authorization: Bearer`` credential — JWT ``id`` claim
         for rmi-backend users, one-way hash for legacy API-key callers.
      3. An IP-derived owner for an unauthenticated caller.

    Every branch returns an id unique to one caller.

    Raises:
        InvalidRequestError: when ``PRY_REQUIRE_AUTH_CREDENTIALS`` is set and
            the request carries no authenticated identity.
    """
    stashed = _stashed_identity(request)
    if stashed:
        return stashed
    token = _bearer_token(request)
    if token:
        return _token_owner(token)
    if _flag(REQUIRE_AUTH_FOR_CREDENTIALS):
        raise InvalidRequestError("Authentication required for credential vault access")
    return _ip_owner(request)


def legacy_owner_count(vault_dir: Path) -> int:
    """Count vault rows still sitting in the shared legacy namespace.

    Operator aid for planning a legacy migration. Read-only: it never
    rewrites, moves or deletes a credential.
    """
    count = 0
    for path in sorted(vault_dir.glob("*.json")):
        try:
            entry = json.loads(path.read_text())
        except (ValueError, OSError):
            logger.warning("credential_scope_exception_handler", exc_info=True)
            continue
        if entry.get("owner", LEGACY_SHARED_OWNER) == LEGACY_SHARED_OWNER:
            count += 1
    return count
