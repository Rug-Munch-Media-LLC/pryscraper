"""Pry - Auth router (credential vault, SSO, CAPTCHA, session health).

Split from api.py on the api-router-split refactor. This file replaces
the inline endpoints that were tagged ["Auth"] in api.py. The behavior
is identical; the new shape is a FastAPI APIRouter that gets included
in the main app.

Endpoints (6):
  POST   /v1/auth/credentials        - store credentials in the vault
  GET    /v1/auth/credentials        - list credentials (no secrets)
  DELETE /v1/auth/credentials/{id}   - delete a credential
  POST   /v1/auth/sso                - generate SSO login script
  POST   /v1/auth/captcha            - solve a CAPTCHA
  POST   /v1/auth/session/health     - check session health

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
from typing import Any

from fastapi import APIRouter, Body, Request

from pry.core.errors import NotFoundError  # type: ignore[import-not-found]
from pry.core.jwt_auth import is_jwt, validate_rmi_jwt

router = APIRouter(tags=["Auth"])


def _request_owner(request: Request) -> str:
    """Derive a stable per-caller owner id for credential-vault scoping.

    Preference order:
      1. Identity stashed on request.state by auth middleware, if present
         (e.g. ``request.state.identity`` / ``request.state.user_id``).
      2. The Authorization header the middleware already validated: JWT
         ``sub`` claim for rmi-backend users, or a one-way SHA-256 hash of
         the token for legacy API-key callers.

    The current middleware (PryHttpMiddleware in api.py) only authenticates
    and does not stash identity, so the header path is the active one.
    Callers with no Authorization header get owner ``""`` (legacy entries).
    """
    state_id = getattr(request.state, "identity", None) or getattr(request.state, "user_id", None)
    if state_id:
        return str(state_id)
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return ""
    token = auth[7:].strip()
    if not token:
        return ""
    if is_jwt(token):
        claims = validate_rmi_jwt(token)
        if claims and claims.get("id"):
            return f"jwt:{claims['id']}"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"key:{digest}"


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
