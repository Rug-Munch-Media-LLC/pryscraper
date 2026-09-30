"""Pry - Auth router (credential vault, SSO, CAPTCHA, session health).

Split from api.py on the api-router-split refactor. This file replaces
the inline endpoints that were tagged ["Auth"] in api.py. The behavior
is identical; the new shape is a FastAPI APIRouter that gets included
in the main app.

Endpoints (8):
  POST   /v1/auth/credentials        - store credentials in the vault
  GET    /v1/auth/credentials        - list credentials (no secrets)
  DELETE /v1/auth/credentials/{id}   - delete a credential
  POST   /v1/auth/sso                - generate SSO login script
  POST   /v1/auth/captcha            - solve a CAPTCHA
  POST   /v1/auth/session/health     - check session health
  POST   /v1/auth/reset-password     - request a password reset token
  POST   /v1/auth/reset-password/confirm - confirm reset with token

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
import hmac
import secrets
import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from pry.core.errors import NotFoundError  # type: ignore[import-not-found]

from .credential_scope import LEGACY_SHARED_OWNER, request_owner as _request_owner

__all__ = [
    "LEGACY_SHARED_OWNER",
    "router",
]

router = APIRouter(tags=["Auth"])

# ── Password reset token cache (in-memory, 1-hour expiry) ──
# Maps token -> {"user_id": str, "expires_at": float}. Tokens are single-use:
# confirm consumes (deletes) the entry. Process-local by design; a restart
# simply invalidates outstanding reset links.
_RESET_TOKEN_TTL_SECONDS = 3600
_RESET_TOKENS: dict[str, dict[str, Any]] = {}

# PBKDF2 parameters for password hashing (stdlib-only, no external deps).
_PBKDF2_ITERATIONS = 390_000


def _hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a random salt.

    Stored format: ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """Verify a password against a ``pbkdf2_sha256$...`` stored hash."""
    try:
        scheme, iterations, salt_hex, hash_hex = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), hash_hex)


@router.post("/v1/auth/credentials", summary="Store credentials in the vault")
async def store_credentials(
    request: Request,
    name: str = Body(...),
    credential_type: str = Body("password"),
    credentials: dict[str, Any] = Body(...),
    target_url: str = Body(""),
) -> dict[str, Any]:
    """Store credentials in the encrypted vault for authenticated scraping.

    Credential types: password, api_key, cookie, token, sso
    Credentials are scoped to the authenticated caller and masked in the
    response (never returned in plaintext).
    """
    from pry.api.auth_connector import store_credential

    result = store_credential(
        name,
        credential_type,
        credentials,
        target_url,
        owner=_request_owner(request),
    )
    return {"success": result["success"], "data": result}


@router.get("/v1/auth/credentials", summary="List stored credentials")
async def list_credentials_endpoint(request: Request) -> dict[str, Any]:
    """List stored credentials scoped to the caller (no secrets exposed)."""
    from pry.api.auth_connector import list_credentials

    creds = list_credentials(owner=_request_owner(request))
    return {"success": True, "data": {"credentials": creds, "total": len(creds)}}


@router.delete("/v1/auth/credentials/{credential_id}", summary="Delete stored credentials")
async def delete_credentials_endpoint(request: Request, credential_id: str) -> dict[str, Any]:
    """Delete a stored credential (owner-scoped; 404 if not found or not owned)."""
    from pry.api.auth_connector import delete_credential

    success = delete_credential(credential_id, owner=_request_owner(request))
    if not success:
        raise NotFoundError(f"Credential not found: {credential_id}")
    return {"success": True, "data": {"deleted": True}}


@router.post("/v1/auth/sso", summary="Generate SSO login script")
async def generate_sso(
    provider: str = Body("okta"),
    username: str = Body(...),
    password: str = Body(...),
    target_url: str = Body(...),
    tenant: str = Body(""),
) -> dict[str, Any]:
    """Generate a browser automation script for SSO login.

    Supports: okta, azure_ad, google_workspace, onelogin
    """
    from pry.api.auth_connector import generate_sso_script

    result = await generate_sso_script(provider, username, password, target_url, tenant)
    return {"success": result["success"], "data": result}


@router.post("/v1/auth/captcha", summary="Solve a CAPTCHA using third-party service")
async def solve_captcha_endpoint(
    image_base64: str = Body(""),
    site_key: str = Body(""),
    page_url: str = Body(""),
    service: str = Body("capsolver"),
    api_key: str = Body(""),
) -> dict[str, Any]:
    """Solve a CAPTCHA using Capsolver or 2Captcha.

    Provide either:
    - image_base64: Base64-encoded CAPTCHA image
    - site_key + page_url: For reCAPTCHA v2
    """
    from pry.api.auth_connector import solve_captcha

    result = await solve_captcha(
        image_base64=image_base64,
        site_key=site_key,
        page_url=page_url,
        service=service,  # type: ignore[arg-type]
        api_key=api_key,
    )
    return {"success": result["success"], "data": result}


@router.post("/v1/auth/session/health", summary="Check authenticated session health")
async def check_session(session_id: str = Body(...)) -> dict[str, Any]:
    """Check the health of an authenticated session.

    Reports cookie validity, session age, and whether re-auth is needed.
    """
    from pry.api.auth_connector import check_session_health

    result = check_session_health(session_id)
    return {"success": True, "data": result}


@router.post("/v1/auth/reset-password", summary="Request a password reset")
async def request_password_reset(email: str = Body(...)) -> dict[str, Any]:
    """Request a password reset token for an account.

    Always returns success regardless of whether the email exists, to avoid
    account enumeration. In production the token would be emailed to the
    user; here it is stored in the in-process reset-token cache with a
    1-hour expiry.
    """
    from pry.core.db.models import User
    from pry.core.db.session import get_session

    with get_session() as session:
        user = session.query(User).filter_by(email=email.strip().lower()).first()
        if user is not None:
            token = secrets.token_urlsafe(32)
            _RESET_TOKENS[token] = {
                "user_id": user.user_id,
                "expires_at": time.time() + _RESET_TOKEN_TTL_SECONDS,
            }
            # TODO(cloud): deliver the reset link via the mail service
            # (compose/mail) instead of relying on the in-process cache.
    return {
        "success": True,
        "message": "If an account exists, a reset link has been sent",
    }


@router.post("/v1/auth/reset-password/confirm", summary="Confirm a password reset")
async def confirm_password_reset(
    token: str = Body(...),
    new_password: str = Body(...),
) -> dict[str, Any]:
    """Complete a password reset using a previously issued token.

    Validates the token (exists, unexpired), enforces a minimum password
    length of 8 characters, hashes the new password with the same PBKDF2
    scheme used across the auth domain, updates the user record, and
    consumes the token (single-use).
    """
    from pry.core.db.models import User
    from pry.core.db.session import get_session

    entry = _RESET_TOKENS.get(token)
    if entry is None or entry["expires_at"] < time.time():
        _RESET_TOKENS.pop(token, None)  # drop expired entries lazily
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="new_password must be at least 8 characters")

    user_id = entry["user_id"]
    with get_session() as session:
        user = session.query(User).filter_by(user_id=user_id).first()
        if user is None:
            _RESET_TOKENS.pop(token, None)
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        user.password_hash = _hash_password(new_password)  # type: ignore[assignment]
        session.commit()

    _RESET_TOKENS.pop(token, None)  # single-use: invalidate after success
    return {"success": True, "message": "Password reset successfully"}
