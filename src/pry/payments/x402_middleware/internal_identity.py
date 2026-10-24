"""Stable first-party service identity for the x402 internal free path.

WHY THIS EXISTS (2026-10-25): the internal HMAC in ``internal.py`` bound the
signed ``caller`` field to the socket peer address. That is correct for a host
process dialing loopback (127.0.0.1, stable forever) and wrong for a container:
the peer is the caller's ephemeral bridge IP, which changes on every container
recreate. A credential whose signed field moves under the client's feet cannot
be provisioned, only hand-patched, and a hand-patched auth field is one recreate
away from a silent 402 in production.

So the caller identity is now a NAMED SERVICE carried in ``X-Internal-Service``
and covered by the same HMAC. A name is stable across recreates, reschedules and
IP churn, and because the header is inside the signed fingerprint it is not
attacker-selectable: only a holder of ``PRY_INTERNAL_TOKEN`` can mint a
signature over it.

SCOPE (``PRY_INTERNAL_ALLOWED_SERVICES``) is an allowlist of service names. A
token is a bearer secret; the allowlist is what stops one compromised first-party
job from impersonating every other one. An absent or empty allowlist disables the
named-service path entirely (fail-closed): callers fall back to the legacy
peer-address binding, which only loopback/host callers can satisfy.

Backwards compatibility is deliberate. A request with NO service header is
resolved by peer address exactly as before, so every existing host-side caller
and every existing gate test keeps its behaviour.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

INTERNAL_SERVICE_HEADER = b"x-internal-service"
ALLOWED_SERVICES_ENV = "PRY_INTERNAL_ALLOWED_SERVICES"


def allowed_services() -> frozenset[str]:
    """Configured service allowlist (lower-cased, comma/space separated)."""
    raw = os.environ.get(ALLOWED_SERVICES_ENV) or ""
    return frozenset(part.strip().lower() for part in raw.replace(",", " ").split() if part.strip())


def requested_service(headers: Mapping[bytes, bytes]) -> str:
    """The service name the caller claims (lower-cased; empty when absent)."""
    return headers.get(INTERNAL_SERVICE_HEADER, b"").decode("latin-1", "replace").strip().lower()


def peer_caller(scope: Mapping[str, Any]) -> str:
    """Derive the caller identity from the ASGI connection (legacy path)."""
    try:
        from pry.payments.x402_middleware.classification import _caller_key_from_scope

        return _caller_key_from_scope(scope)
    except ImportError:  # pragma: no cover - partial import during startup
        client = scope.get("client") or ()
        return str(client[0]) if client and client[0] else ""


def resolve_caller(scope: Mapping[str, Any], headers: Mapping[bytes, bytes]) -> str | None:
    """The caller field to sign and verify, or None when the claim is not allowed.

    A claimed service must appear in the allowlist. An unlisted name is a hard
    reject (None), never a silent fall back to the peer address, so a caller
    cannot dodge the allowlist by claiming a name we do not serve.
    """
    service = requested_service(headers)
    if not service:
        return peer_caller(scope)
    if service not in allowed_services():
        logger.warning(
            "pry_internal_service_denied",
            extra={"service": service, "path": str(scope.get("path", ""))},
        )
        return None
    return service


def audit_grant(caller: str, method: str, path: str) -> None:
    """Record a granted first-party bypass: one structured line per request."""
    logger.info(
        "pry_internal_grant",
        extra={"caller": caller, "method": method.upper(), "path": path, "principal": "internal"},
    )


def mark_principal(scope: dict[str, Any], caller: str) -> None:
    """Stamp the resolved service onto the scope's payment marker.

    The rate limiter buckets on ``x402_verified['caller']``. Stamping it gives
    each first-party service its OWN budget instead of one shared pseudo-tenant
    bucket, so a runaway job cannot starve the other services.
    """
    marker = scope.get("x402_verified")
    if isinstance(marker, dict):
        marker["caller"] = caller
        marker["internal"] = True


__all__ = [
    "ALLOWED_SERVICES_ENV",
    "INTERNAL_SERVICE_HEADER",
    "allowed_services",
    "audit_grant",
    "mark_principal",
    "peer_caller",
    "requested_service",
    "resolve_caller",
]
