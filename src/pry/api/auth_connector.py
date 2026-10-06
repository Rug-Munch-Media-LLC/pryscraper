"""Pry — Enterprise SSO / Auth Connector System.
SSO flow automation, CAPTCHA integration, session health.

The credential vault itself now lives in ``pry.api.credential_vault``; the
public vault names are re-exported here so existing importers keep working.
That module also holds the owner-scoping rules that stop anonymous callers
sharing one namespace.

Part of Pry — Stealth / Anti-Detection Module
Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
Change Date: 2029-01-01 (converts to MIT).
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from pry.api.credential_vault import (
    VAULT_DIR,
    delete_credential,
    get_credential,
    list_credentials,
    store_credential,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SSO_PROVIDERS",
    "VAULT_DIR",
    "check_session_health",
    "delete_credential",
    "generate_sso_script",
    "get_credential",
    "list_credentials",
    "solve_captcha",
    "store_credential",
]

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
    from pry.api.client import get_client

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
        logger.warning("auth_connector_exception_handler", exc_info=True)
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
    from pry.engine.sessions import load_session

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
        except (ValueError, TypeError) as e:
            logger.warning("auth_session_age_parse_failed", extra={"error": str(e)[:160]})

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
