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

from typing import Any

from fastapi import APIRouter, Body

from errors import NotFoundError  # type: ignore[import-not-found]

router = APIRouter(tags=["Auth"])


@router.post("/v1/auth/credentials", summary="Store credentials in the vault")
async def store_credentials(
    name: str = Body(...),
    credential_type: str = Body("password"),
    credentials: dict[str, Any] = Body(...),
    target_url: str = Body(""),
) -> dict[str, Any]:
    """Store credentials in the encrypted vault for authenticated scraping.

    Credential types: password, api_key, cookie, token, sso
    """
    from auth_connector import store_credential

    result = store_credential(name, credential_type, credentials, target_url)
    return {"success": result["success"], "data": result}


@router.get("/v1/auth/credentials", summary="List stored credentials")
async def list_credentials_endpoint() -> dict[str, Any]:
    """List all stored credentials (without exposing secrets)."""
    from auth_connector import list_credentials

    creds = list_credentials()
    return {"success": True, "data": {"credentials": creds, "total": len(creds)}}


@router.delete(
    "/v1/auth/credentials/{credential_id}", summary="Delete stored credentials"
)
async def delete_credentials_endpoint(credential_id: str) -> dict[str, Any]:
    """Delete stored credentials from the vault."""
    from auth_connector import delete_credential

    success = delete_credential(credential_id)
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
    from auth_connector import generate_sso_script

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
    from auth_connector import solve_captcha

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
    from auth_connector import check_session_health

    result = check_session_health(session_id)
    return {"success": True, "data": result}
