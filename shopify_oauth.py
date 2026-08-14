"""Pry — Shopify OAuth helper.

Implements the public-app OAuth dance Shopify uses for embedded apps:
  1. install_url()  — build the authorize URL the merchant is redirected to.
  2. exchange_code() — trade the `code` callback param for an access token.
  3. verify_webhook_hmac() — verify X-Shopify-Hmac-SHA256 on incoming webhooks.

Commerce code (commerce_sync.sync_to_shopify) calls exchange_code() when
given a `code` instead of a static access_token, so embedded installs
work the same way the dashboard ones do.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

SHOPIFY_OAUTH_AUTHORIZE_URL = "https://{shop}/admin/oauth/authorize"
SHOPIFY_OAUTH_TOKEN_URL = "https://{shop}/admin/oauth/access_token"  # noqa: S105 - URL constant, not a credential
SHOPIFY_API_VERSION = "2024-01"

DEFAULT_SCOPES = [
    "read_products",
    "write_products",
    "read_inventory",
    "write_inventory",
]


def install_url(
    shop_domain: str,
    redirect_uri: str,
    scopes: list[str] | None = None,
    api_key: str = "",
    api_secret: str = "",
) -> str:
    """Build the Shopify OAuth install URL.

    Args:
        shop_domain: Bare shop domain (e.g. "mystore.myshopify.com").
        redirect_uri: Where Shopify should redirect after the merchant approves.
        scopes: List of OAuth scopes. Defaults to DEFAULT_SCOPES.
        api_key: Public app API key. Required.
        api_secret: Public app API secret. Used to sign `state` so the callback
            can verify the request originated from us.

    Returns:
        Fully qualified authorize URL with state nonce.
    """
    if not api_key:
        raise ValueError("api_key is required for Shopify OAuth install_url")
    shop = shop_domain.strip().lower().rstrip("/")
    if not shop.endswith(".myshopify.com"):
        raise ValueError(f"shop_domain must end with .myshopify.com, got: {shop_domain}")

    state = secrets.token_urlsafe(24)
    params: dict[str, str] = {
        "client_id": api_key,
        "scope": ",".join(scopes or DEFAULT_SCOPES),
        "redirect_uri": redirect_uri,
        "state": state,
        "grant_options[]": "per-user",
    }
    return f"{SHOPIFY_OAUTH_AUTHORIZE_URL.format(shop=shop)}?{urlencode(params)}"


def exchange_code(
    shop_domain: str,
    code: str,
    api_key: str = "",
    api_secret: str = "",
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Exchange a Shopify OAuth callback `code` for a permanent access token.

    Args:
        shop_domain: Bare shop domain (e.g. "mystore.myshopify.com").
        code: The `code` query parameter from the OAuth callback.
        api_key: Public app API key.
        api_secret: Public app API secret. Required by Shopify.
        timeout: HTTP timeout in seconds.

    Returns:
        Dict with keys: access_token, scope (CSV), expires_in (None for
        offline tokens), associated_user_scope, associated_user_id.

    Raises:
        httpx.HTTPError: if the token exchange fails.
        ValueError: on missing arguments or malformed shop domain.
    """
    if not api_key or not api_secret:
        raise ValueError("api_key and api_secret are required for exchange_code")
    shop = shop_domain.strip().lower().rstrip("/")
    if not shop.endswith(".myshopify.com"):
        raise ValueError(f"shop_domain must end with .myshopify.com, got: {shop_domain}")

    url = SHOPIFY_OAUTH_TOKEN_URL.format(shop=shop)
    payload = {
        "client_id": api_key,
        "client_secret": api_secret,
        "code": code,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise ValueError(f"Shopify OAuth response missing access_token: {data}")
    return data


def verify_webhook_hmac(
    data_bytes: bytes,
    hmac_header: str,
    api_secret: str,
) -> bool:
    """Verify the X-Shopify-Hmac-SHA256 header on an incoming webhook.

    Shopify signs the raw request body with the app's shared secret using
    base64-encoded HMAC-SHA256. This function recomputes and compares in
    constant time.

    Args:
        data_bytes: Raw request body bytes (NOT parsed JSON).
        hmac_header: Value of the X-Shopify-Hmac-SHA256 header.
        api_secret: Public app API secret.

    Returns:
        True if the signature is valid; False otherwise.
    """
    if not hmac_header or not api_secret:
        return False
    import base64

    digest = hmac.new(api_secret.encode("utf-8"), data_bytes, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, hmac_header.strip())
