"""Positive credential validation for the x402 gate.

The gate is the REVENUE boundary: it may only wave a Bearer-credentialed
request through to the paid resource once it has positively validated the
credential itself. A prefix/length test (``Bearer <anything>``) is not
validation — it hands the money path to a request nobody has authenticated.

``valid_api_key_credential`` answers one question: *is this token a currently
valid credential?* It deliberately mirrors ONLY the key-based branches of
``pry.core.middleware_auth.request_authorized``:

* a DB-issued ``pry_*`` key that ``api_keys_service.authenticate`` still
  resolves (unknown, revoked and expired keys all resolve to ``None``),
* the operator's master key (``settings.api_key``), constant-time compared,
* an rmi JWT that ``validate_rmi_jwt`` still accepts.

It intentionally does NOT reproduce the inner layer's *keyless* loopback
fallback: a socket peer is not a credential, so a loopback caller with an
invented bearer token is not authenticated and must be 402-challenged. This is
what makes the gate safe on its own, independent of how the app is deployed
behind it.

FAIL CLOSED: any store/JWT/import error denies. A validation that cannot be
performed is never a pass.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

import hmac
import logging
from typing import Any

from pry.core.settings import settings

logger = logging.getLogger(__name__)

BEARER_PREFIX = "bearer "
MIN_BEARER_CREDENTIAL_LEN = 8


def bearer_credential(headers: dict[bytes, bytes]) -> str:
    """Return the token carried by a ``Bearer`` header, or ``""``.

    Case-insensitive on the scheme (RFC 7235 says the scheme is
    case-insensitive) and whitespace-normalised. Returns ``""`` for any
    header that is not a syntactically plausible Bearer credential, so
    callers never have to re-implement the prefix test.
    """
    raw = headers.get(b"authorization", b"").decode("latin-1", "replace").strip()
    if not raw.lower().startswith(BEARER_PREFIX):
        return ""
    token = raw[len(BEARER_PREFIX) :].strip()
    if len(token) < MIN_BEARER_CREDENTIAL_LEN:
        return ""
    return token


def _valid_db_key(token: str) -> bool:
    """True when the token is a live DB-issued ``pry_*`` key."""
    from pry.core.api_keys_service import authenticate

    return authenticate(token) is not None


def _valid_master_key(token: str) -> bool:
    """True when the token is the operator's configured master key."""
    master = settings.api_key
    if not master:
        return False
    return hmac.compare_digest(token.encode("utf-8"), master.encode("utf-8"))


def _valid_rmi_jwt(token: str) -> bool:
    """True when the token is an unexpired, correctly signed rmi JWT."""
    from pry.core.jwt_auth import validate_rmi_jwt

    return validate_rmi_jwt(token) is not None


def _valid_checks() -> tuple[tuple[str, Any], ...]:
    """Credential validators, most specific first."""
    return (
        ("db_api_key", _valid_db_key),
        ("master_key", _valid_master_key),
        ("rmi_jwt", _valid_rmi_jwt),
    )


def valid_api_key_credential(headers: dict[bytes, bytes]) -> bool:
    """True when the request presents a currently valid Bearer credential.

    Fail-closed by construction: a missing/malformed header is ``False``, and
    any exception raised by a credential store or JWT verifier is logged and
    counted as a rejection rather than waved through. Ordering matters — the
    DB-key lookup runs only for ``pry_``-shaped tokens so a foreign scheme
    never reaches the database.
    """
    token = bearer_credential(headers)
    if not token:
        return False
    for name, check in _valid_checks():
        # The DB-key check is cheap and self-limiting; the master-key and JWT
        # checks are skipped for ``pry_`` tokens that already authenticated so
        # a revoked DB key is not re-admitted by a wider check.
        if name == "db_api_key" and not token.startswith("pry_"):
            continue
        if name != "db_api_key" and token.startswith("pry_"):
            continue
        try:
            if check(token):
                return True
        except Exception as e:  # noqa: BLE001 - a store/JWT outage must deny, never grant
            logger.warning(
                "x402_credential_validation_failed",
                extra={"validator": name, "error": str(e)},
            )
    return False
