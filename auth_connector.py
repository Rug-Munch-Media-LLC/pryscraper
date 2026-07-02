"""Pry — Enterprise SSO / Auth Connector System.
Credential vault, session persistence, SSO flow automation, CAPTCHA integration."""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import httpx

from paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

VAULT_DIR = PRY_DATA_DIR / "vault"
VAULT_DIR.mkdir(parents=True, exist_ok=True)

# ── Credential Vault (encrypted at rest) ──


def _vault_path(credential_id: str) -> Path:
    return VAULT_DIR / f"{credential_id}.json"


def store_credential(
    name: str,
    credential_type: str,
    credentials: dict[str, Any],
    target_url: str = "",
) -> dict[str, Any]:
    """Store credentials in the vault.

    Args:
        name: Human-readable name for this credential
        credential_type: "password", "api_key", "cookie", "token", "sso"
        credentials: Dict containing the credential details
        target_url: The URL these credentials are for

    In production, this would encrypt at rest. For now, stores as JSON
    with a warning about production use.
    """
    credential_id = uuid.uuid4().hex[:12]
    entry = {
        "id": credential_id,
        "name": name,
        "type": credential_type,
        "target_url": target_url,
        "credentials": credentials,
        "created_at": datetime.now(UTC).isoformat(),
        "last_used": None,
        "use_count": 0,
        "note": "WARNING: Credentials stored in plaintext. Enable encryption for production use.",
    }
    try:
        path = _vault_path(credential_id)
        path.write_text(json.dumps(entry, indent=2))
        logger.info(
            "credential_stored",
            extra={
                "credential_id": credential_id,
                "credential_name": name,
                "type": credential_type,
            },
        )
        return {"success": True, "credential_id": credential_id, "credential": entry}
    except OSError as e:
        return {"success": False, "error": str(e)}


def get_credential(credential_id: str) -> dict[str, Any] | None:
    """Retrieve credentials from the vault."""
    path = _vault_path(credential_id)
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text())
        entry["last_used"] = datetime.now(UTC).isoformat()
        entry["use_count"] = entry.get("use_count", 0) + 1
        path.write_text(json.dumps(entry, indent=2))
        return cast("dict[str, Any]", entry)
    except (json.JSONDecodeError, OSError):
        return None


def delete_credential(credential_id: str) -> bool:
    """Delete credentials from the vault."""
    path = _vault_path(credential_id)
    if path.exists():
        path.unlink()
        logger.info("credential_deleted", extra={"credential_id": credential_id})
        return True
    return False


def list_credentials() -> list[dict[str, Any]]:
    """List all stored credentials (without exposing secrets)."""
    credentials = []
    for path in sorted(VAULT_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            entry = json.loads(path.read_text())
            credentials.append(
                {
                    "id": entry["id"],
                    "name": entry["name"],
                    "type": entry["type"],
                    "target_url": entry.get("target_url", ""),
                    "created_at": entry["created_at"],
                    "last_used": entry.get("last_used"),
                    "use_count": entry.get("use_count", 0),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return credentials


# ── SSO Flow Automation ──

SSO_PROVIDERS = {
    "okta": {
        "name": "Okta",
        "login_url_pattern": "{domain}/login/login.htm",
        "auth_method": "saml",
    },
    "azure_ad": {
        "name": "Azure Active Directory",
        "login_url_pattern": "{domain}/login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "auth_method": "oidc",
    },
    "google_workspace": {
        "name": "Google Workspace",
        "login_url_pattern": "https://accounts.google.com/o/oauth2/auth",
        "auth_method": "oidc",
    },
    "onelogin": {
        "name": "OneLogin",
        "login_url_pattern": "{domain}/login",
        "auth_method": "saml",
    },
}


async def generate_sso_script(
    provider: str,
    username: str,
    password: str,
    target_url: str,
    tenant: str = "",
    domain: str = "",
) -> dict[str, Any]:
    """Generate a Playwright script for SSO authentication flow.

    Returns JavaScript that can be injected into a browser page
    to automate the SSO login flow.
    """
    if provider not in SSO_PROVIDERS:
        return {"success": False, "error": f"Unsupported SSO provider: {provider}"}

    provider_info = SSO_PROVIDERS[provider]
    domain = domain or target_url.split("/")[2] if "//" in target_url else target_url

    login_url = provider_info["login_url_pattern"].format(domain=domain, tenant=tenant)

    script = f"""
    (async () => {{
        const delay = ms => new Promise(r => setTimeout(r, ms));

        // Navigate to SSO login
        window.location.href = "{login_url}";
        await delay(3000);

        // Fill credentials (customize selectors for the provider)
        const usernameField = document.querySelector('input[type="email"], input[name="username"], input[name="loginfmt"]');
        const passwordField = document.querySelector('input[type="password"], input[name="password"], input[name="passwd"]');
        const submitButton = document.querySelector('button[type="submit"], input[type="submit"], [data-report-event="SignIn_Submit"]');

        if (usernameField && passwordField) {{
            usernameField.value = "{username}";
            await delay(500);
            passwordField.value = "{password}";
            await delay(500);
            if (submitButton) submitButton.click();
        }}

        // Wait for redirect
        await delay(5000);
    }})();
    """

    return {
        "success": True,
        "provider": provider,
        "login_url": login_url,
        "script": script,
        "note": "This script performs SSO login. Use with Pry's /v1/automate endpoint.",
    }


# ── CAPTCHA Integration ──


async def solve_captcha(
    image_base64: str = "",
    site_key: str = "",
    page_url: str = "",
    service: Literal["capsolver", "2captcha"] = "capsolver",
    api_key: str = "",
) -> dict[str, Any]:
    """Solve a CAPTCHA using a third-party service.

    Supports Capsolver and 2Captcha.
    Returns the solution token.
    """
    if not api_key:
        return {"success": False, "error": f"{service} API key required"}

    if service == "capsolver":
        return await _solve_capsolver(image_base64, site_key, page_url, api_key)
    elif service == "2captcha":
        return await _solve_2captcha(image_base64, site_key, page_url, api_key)
    else:
        return {"success": False, "error": f"Unknown service: {service}"}


async def _solve_capsolver(
    image_base64: str, site_key: str, page_url: str, api_key: str
) -> dict[str, Any]:
    """Solve CAPTCHA via Capsolver API."""
    from client import get_client

    client = await get_client()

    if image_base64:
        task = {
            "type": "ImageToTextTask",
            "body": image_base64[:100000] if len(image_base64) > 100000 else image_base64,
        }
    elif site_key and page_url:
        task = {
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteKey": site_key,
            "websiteURL": page_url,
        }
    else:
        return {"success": False, "error": "Provide image_base64 or site_key + page_url"}

    try:
        resp = await client.post(
            "https://api.capsolver.com/createTask",
            json={"clientKey": api_key, "task": task},
            timeout=30,
        )
        data = resp.json()
        task_id = data.get("taskId")
        if not task_id:
            return {"success": False, "error": data.get("errorDescription", "Capsolver error")}

        for _ in range(30):
            await asyncio.sleep(2)
            result_resp = await client.post(
                "https://api.capsolver.com/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
            )
            result_data = result_resp.json()
            if result_data.get("status") == "ready":
                return {
                    "success": True,
                    "token": result_data["solution"].get("gRecaptchaResponse", ""),
                }
            if result_data.get("status") == "failed":
                return {"success": False, "error": "CAPTCHA solving failed"}

        return {"success": False, "error": "CAPTCHA solving timed out"}
    except (httpx.HTTPError, httpx.RequestError) as e:
        return {"success": False, "error": str(e)[:200]}


async def _solve_2captcha(
    image_base64: str, site_key: str, page_url: str, api_key: str
) -> dict[str, Any]:
    """Solve CAPTCHA via 2Captcha API."""
    return {"success": False, "error": "2Captcha support coming soon. Use Capsolver."}


# ── Session Health Monitoring ──


def check_session_health(session_id: str) -> dict[str, Any]:
    """Check the health of an authenticated session.

    Returns session age, last used, cookie count, and stale status.
    """
    from sessions import load_session

    data = asyncio.run(load_session(session_id))
    if not data:
        return {"healthy": False, "error": "Session not found"}

    cookies = data.get("cookies", [])
    saved_at = data.get("saved_at", "")

    now = time.time()
    valid_cookies = 0
    expired_cookies = 0
    for cookie in cookies:
        expiry = cookie.get("expires", 0)
        if expiry and expiry < now:
            expired_cookies += 1
        else:
            valid_cookies += 1

    age_hours = 0.0
    if saved_at:
        try:
            saved_dt = datetime.fromisoformat(saved_at)
            age_hours = (datetime.now(UTC) - saved_dt).total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    healthy = valid_cookies > 0 and age_hours < 24

    return {
        "session_id": session_id,
        "healthy": healthy,
        "total_cookies": len(cookies),
        "valid_cookies": valid_cookies,
        "expired_cookies": expired_cookies,
        "age_hours": round(age_hours, 1),
        "stale": age_hours > 24,
        "note": "Session is healthy" if healthy else "Session needs re-authentication",
    }
