"""Pry JWT Authentication — validates tokens issued by rmi-backend.

Dual-mode: accepts both the legacy PRY_API_KEY and JWT tokens from rmi-backend.

Usage:
    from pry.core.jwt_auth import validate_pry_token

    # In middleware:
    claims = validate_pry_token(token)
    if claims:
        # Authenticated via JWT (rmi-backend user)
        user_id = claims["id"]
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Any

try:
    import jwt as pyjwt

    _HAS_JWT = True
except ImportError:
    pyjwt = None  # type: ignore[assignment]
    _HAS_JWT = False

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_JWT_ALGORITHM: str = os.getenv("PRY_JWT_ALGORITHM", "RS256")
_JWT_PUBLIC_KEY: str = os.getenv("PRY_JWT_PUBLIC_KEY", "")
_JWKS_URL: str = os.getenv("PRY_JWKS_URL", "https://rugmunch.io/.well-known/jwks.json")
_JWKS_CACHE_TTL: int = int(os.getenv("PRY_JWKS_CACHE_TTL", "3600"))

# SECURITY (2026-08-20 audit, P0-4): RS256 ONLY — enforced fail-closed at
# startup. The old code silently fell back to HS256 for any non-RS256 value,
# using the RSA *public* key as the HMAC secret — the classic
# algorithm-confusion attack: the public key is served on a public JWKS
# endpoint, so anyone who could read it could forge valid tokens. A
# non-RS256 PRY_JWT_ALGORITHM is therefore a fatal misconfiguration: refuse
# to start instead of ever validating a token with it.
if _JWT_ALGORITHM != "RS256":
    raise RuntimeError(
        f"PRY_JWT_ALGORITHM={_JWT_ALGORITHM!r} is not supported: only RS256 is "
        "allowed. The HS256 fallback was removed (algorithm-confusion forgery, "
        "2026-08-20 security audit). Unset PRY_JWT_ALGORITHM or set it to 'RS256'."
    )

# Cache
_jwks_cache: dict[str, Any] = {"key": None, "fetched_at": 0.0}


def _load_key(key_or_path: str) -> str:
    if os.path.exists(key_or_path) and os.path.isfile(key_or_path):
        with open(key_or_path) as _f:
            return _f.read()
    return key_or_path


def _fetch_public_key() -> str | None:
    """Fetch the RSA public key from env var or JWKS endpoint."""
    now = time.time()
    if _jwks_cache["key"] and (now - _jwks_cache["fetched_at"]) < _JWKS_CACHE_TTL:
        return _jwks_cache["key"]

    if _JWT_PUBLIC_KEY:
        key = _load_key(_JWT_PUBLIC_KEY)
        _jwks_cache["key"] = key
        _jwks_cache["fetched_at"] = now
        return key

    try:
        # Only allow http/https for the JWKS endpoint (blocks file:/custom schemes — S310).
        if not _JWKS_URL.startswith(("http://", "https://")):
            logger.warning("JWKS URL uses unsupported scheme; refusing to fetch")
            return None
        req = urllib.request.Request(_JWKS_URL, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 — scheme guard above restricts to http/https
            data = json.loads(resp.read().decode())
        if "pem" in data:
            _jwks_cache["key"] = data["pem"]
            _jwks_cache["fetched_at"] = now
            return data["pem"]
        logger.warning("JWKS endpoint returned no PEM field")
    except Exception as exc:  # noqa: BLE001 - JWKS fetch failure is logged; caller falls back to API key auth
        logger.warning("Failed to fetch JWKS: %s", exc)

    return None


def validate_rmi_jwt(token: str) -> dict[str, Any] | None:
    """Validate a JWT issued by rmi-backend.

    Args:
        token: Raw JWT string (without 'Bearer ' prefix).

    Returns:
        User claims dict or None if invalid.
    """
    if not _HAS_JWT or not token:
        return None

    key = _fetch_public_key()
    if not key:
        logger.warning("No public key configured for JWT validation")
        return None

    # SECURITY (2026-08-20 audit, P0-4): RS256 ONLY, fail-closed. A non-RS256
    # PRY_JWT_ALGORITHM already aborts process startup (see module top) — this
    # runtime guard is defense-in-depth against the module constant being
    # altered after import. The old code fell back to HS256 for any non-RS256
    # value, using the RSA *public* key as the HMAC secret — the classic
    # algorithm-confusion attack: anyone holding the public key (it is served
    # on a public JWKS endpoint) could forge valid tokens.
    if _JWT_ALGORITHM != "RS256":
        logger.error(
            "Unsupported PRY_JWT_ALGORITHM %r — only RS256 is allowed; refusing token",
            _JWT_ALGORITHM,
        )
        return None
    try:
        # require=["exp"]: tokens without an expiry claim are rejected —
        # a leaked token must not grant forever-access.
        payload = pyjwt.decode(token, key, algorithms=["RS256"], options={"require": ["exp"]})
    except Exception as exc:  # noqa: BLE001 - any decode failure means invalid token; logged at debug
        logger.debug("JWT validation failed: %s", exc)
        return None

    return {
        "id": payload.get("sub", ""),
        "email": payload.get("email", ""),
        "tier": payload.get("tier", "FREE"),
        "role": payload.get("role", "USER"),
        "wallet": payload.get("wallet"),
    }


def is_jwt(token: str) -> bool:
    """Heuristic check: JWTs have 3 dot-separated base64 segments.

    API keys (pry_*, wp_*) don't match this pattern.
    """
    if not token:
        return False
    parts = token.split(".")
    return len(parts) == 3 and all(len(p) > 0 for p in parts)
