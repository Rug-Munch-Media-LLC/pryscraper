"""Pry — Proxy router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Proxy"])

# Fields on ProxyManager.active_config that must never be returned to a
# client in plaintext (credentials used to reach the proxy/egress provider).
_SENSITIVE_CONFIG_FIELDS: frozenset[str] = frozenset({"username", "password", "api_key"})


def require_sensitive_config_auth(request: Request) -> None:
    """Fail-closed guard for egress configuration endpoints.

    Mirrors the app middleware (api.py request_authorized): with PRY_API_KEY
    set, a valid Bearer credential is required from any source; without a key,
    only loopback clients may change proxy/tor egress configuration.
    """
    from api import request_authorized

    if not request_authorized(request.scope):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: valid API key required (or loopback client when no key is configured)",
        )


@router.get("/v1/proxy/providers", tags=["Proxy"], summary="List all available proxy providers")
async def list_proxy_providers() -> dict[str, Any]:
    """List free + premium proxy providers with affiliate details."""
    from proxy_manager import ProxyManager

    return {"success": True, "data": ProxyManager().list_providers()}


@router.post(
    "/v1/proxy/signup", tags=["Proxy"], summary="Open affiliate signup link for a provider"
)
async def proxy_signup(provider: str = Body(...)) -> dict[str, Any]:
    """Get the affiliate signup URL for a proxy provider.

    Records a click for revenue tracking. The user can then sign up at that URL
    and come back to configure credentials.
    """
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    url = pm.get_signup_link(provider)
    return {"success": True, "data": {"signup_url": url, "provider": provider}}


@router.get(
    "/v1/proxy/referrals", tags=["Proxy"], summary="List proxy provider affiliate referrals"
)
async def list_proxy_referrals() -> dict[str, Any]:
    """Return the curated proxy provider affiliate catalog (proxy_referrals.py).

    This is the marketing-friendly subset: commission, promo codes, tier
    (premium/standard/budget), and referral URLs. Useful for a "Sign up via Pry
    and we get a cut" UI, or for showing users premium options when their free
    proxy fails.

    The full connection metadata (host, port, auth) lives in /v1/proxy/providers.
    """
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    return {
        "success": True,
        "data": {
            "providers": pm.list_proxy_referrals(),
            "summary": pm.get_proxy_referral_summary(),
        },
    }


@router.get(
    "/v1/proxy/referrals/{tag}", tags=["Proxy"], summary="Get a single proxy provider referral"
)
async def get_proxy_referral(tag: str) -> dict[str, Any]:
    """Return the affiliate info for a single proxy provider by tag."""
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    info = pm.get_proxy_referral(tag)
    if not info:
        return {"success": False, "error": f"No proxy referral found for tag: {tag}"}
    return {"success": True, "data": {"tag": tag, **info}}


@router.post(
    "/v1/proxy/configure",
    tags=["Proxy"],
    summary="Configure proxy credentials",
    dependencies=[Depends(require_sensitive_config_auth)],
)
async def proxy_configure(
    provider: str = Body(...),
    username: str = Body(""),
    password: str = Body(""),
    api_key: str = Body(""),
    proxy_url: str = Body(""),
) -> dict[str, Any]:
    """Configure credentials for a premium proxy provider.

    After signing up via /v1/proxy/signup, the user provides their credentials here.
    """
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    creds = {"username": username, "password": password, "api_key": api_key, "proxy_url": proxy_url}
    creds = {k: v for k, v in creds.items() if v}
    result = pm.select_provider(provider, creds)
    return {"success": result["success"], "data": result}


@router.get("/v1/proxy/test", tags=["Proxy"], summary="Test the active proxy")
async def proxy_test() -> dict[str, Any]:
    """Test the currently configured proxy and return its public IP."""
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    proxy_url = pm.get_proxy_url()
    if not proxy_url:
        return {"success": True, "data": {"active": False, "message": "No proxy configured"}}
    result = pm.test_proxy(proxy_url)
    return {"success": True, "data": {"active": True, **result}}


@router.get("/v1/proxy/pool", tags=["Proxy"], summary="List the Webshare residential proxy pool")
async def proxy_pool() -> dict[str, Any]:
    """Return the Webshare residential proxy pool (credentials masked).

    Loaded from the WEBSHARE_PROXY_LIST env var or, best-effort, from
    the secrets manager (path via PRY_WEBSHARE_GOPASS_PATH). Cached per process.
    """
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    return {"success": True, "data": pm.webshare_pool_info()}


@router.get("/v1/proxy/status", tags=["Proxy"], summary="Get current proxy status")
async def proxy_status() -> dict[str, Any]:
    """Get current proxy configuration and available providers.

    Credential fields (username/password/api_key) are redacted to "***".
    """
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    active_config = dict(pm.active_config.__dict__)
    for field in _SENSITIVE_CONFIG_FIELDS:
        if active_config.get(field):
            active_config[field] = "***"
    return {
        "success": True,
        "data": {
            "active_config": active_config,
            "configured_providers": list(pm.credentials.keys()),
            "available_providers": pm.list_providers(),
        },
    }


@router.post(
    "/v1/proxy/recommend", tags=["Proxy"], summary="Get proxy recommendation after a block"
)
async def proxy_recommend(last_error: str = Body("")) -> dict[str, Any]:
    """After a scrape fails with anti-bot detection, get a recommendation
    for which premium proxy provider to sign up with."""
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    rec = pm.get_recommendation(last_error)
    return {"success": True, "data": rec}


@router.get("/v1/proxy/clicks", tags=["Proxy"], summary="Get recent proxy referral clicks")
async def proxy_clicks(days_back: int = 30) -> dict[str, Any]:
    """Get recent proxy referral clicks for revenue tracking."""
    from proxy_manager import ProxyManager

    pm = ProxyManager()
    clicks = pm.get_recent_clicks(days_back=days_back)
    return {
        "success": True,
        "data": {
            "total_clicks": len(clicks),
            "days_back": days_back,
            "clicks": clicks,
        },
    }
