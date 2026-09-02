# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the Shopify OAuth helper (pry.commerce.shopify_oauth).

Covers the public-app OAuth dance:
  - install_url()  — authorize URL construction, scope/state params, shop validation
  - exchange_code() — token exchange (success + error paths), shop validation
  - verify_webhook_hmac() — HMAC-SHA256 webhook signature verification

All HTTP is mocked with respx — no live network.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from pry.commerce import shopify_oauth

API_KEY = "test-api-key-123"
API_SECRET = "test-api-secret-456"
SHOP = "mystore.myshopify.com"
REDIRECT_URI = "https://app.example.com/auth/callback"


# ── install_url ────────────────────────────────────────────────────────


def test_install_url_builds_authorize_url() -> None:
    url = shopify_oauth.install_url(SHOP, REDIRECT_URI, api_key=API_KEY, api_secret=API_SECRET)
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == SHOP
    assert parsed.path == "/admin/oauth/authorize"

    params = parse_qs(parsed.query)
    assert params["client_id"] == [API_KEY]
    assert params["redirect_uri"] == [REDIRECT_URI]
    # Default scopes joined by comma
    assert params["scope"] == [",".join(shopify_oauth.DEFAULT_SCOPES)]
    assert params["grant_options[]"] == ["per-user"]
    # state is a non-empty random nonce
    assert len(params["state"][0]) > 0


def test_install_url_uses_custom_scopes() -> None:
    url = shopify_oauth.install_url(
        SHOP, REDIRECT_URI, scopes=["read_orders", "write_orders"], api_key=API_KEY
    )
    params = parse_qs(urlparse(url).query)
    assert params["scope"] == ["read_orders,write_orders"]


def test_install_url_state_is_random_per_call() -> None:
    url1 = shopify_oauth.install_url(SHOP, REDIRECT_URI, api_key=API_KEY)
    url2 = shopify_oauth.install_url(SHOP, REDIRECT_URI, api_key=API_KEY)
    state1 = parse_qs(urlparse(url1).query)["state"][0]
    state2 = parse_qs(urlparse(url2).query)["state"][0]
    assert state1 != state2


def test_install_url_normalizes_shop_domain() -> None:
    url = shopify_oauth.install_url("  MyStore.Myshopify.com/ ", REDIRECT_URI, api_key=API_KEY)
    parsed = urlparse(url)
    assert parsed.netloc == "mystore.myshopify.com"


def test_install_url_rejects_missing_api_key() -> None:
    with pytest.raises(ValueError, match="api_key is required"):
        shopify_oauth.install_url(SHOP, REDIRECT_URI, api_key="")


def test_install_url_rejects_non_shopify_domain() -> None:
    with pytest.raises(ValueError, match=r"must end with \.myshopify\.com"):
        shopify_oauth.install_url("example.com", REDIRECT_URI, api_key=API_KEY)


# ── exchange_code ──────────────────────────────────────────────────────


@respx.mock
def test_exchange_code_success() -> None:
    token_url = f"https://{SHOP}/admin/oauth/access_token"
    respx.post(token_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "shpat_abc123",
                "scope": "read_products,write_products",
                "expires_in": None,
                "associated_user_scope": "read_products",
                "associated_user_id": 42,
            },
        )
    )

    data = shopify_oauth.exchange_code(SHOP, "callback-code", API_KEY, API_SECRET)

    assert data["access_token"] == "shpat_abc123"
    assert data["scope"] == "read_products,write_products"
    assert data["expires_in"] is None
    assert data["associated_user_id"] == 42

    # Verify the request payload sent to Shopify
    request = respx.calls.last.request
    assert request.url == token_url
    assert request.method == "POST"
    assert request.content is not None
    import json

    payload = json.loads(request.content)
    assert payload["client_id"] == API_KEY
    assert payload["client_secret"] == API_SECRET
    assert payload["code"] == "callback-code"


@respx.mock
def test_exchange_code_missing_access_token_raises() -> None:
    respx.post(f"https://{SHOP}/admin/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"error": "invalid_grant"})
    )
    with pytest.raises(ValueError, match="missing access_token"):
        shopify_oauth.exchange_code(SHOP, "bad-code", API_KEY, API_SECRET)


@respx.mock
def test_exchange_code_http_error_raises() -> None:
    respx.post(f"https://{SHOP}/admin/oauth/access_token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_request"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        shopify_oauth.exchange_code(SHOP, "code", API_KEY, API_SECRET)


@respx.mock
def test_exchange_code_network_error_raises() -> None:
    respx.post(f"https://{SHOP}/admin/oauth/access_token").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    with pytest.raises(httpx.HTTPError):
        shopify_oauth.exchange_code(SHOP, "code", API_KEY, API_SECRET)


def test_exchange_code_requires_api_key_and_secret() -> None:
    with pytest.raises(ValueError, match="api_key and api_secret are required"):
        shopify_oauth.exchange_code(SHOP, "code", api_key="", api_secret="")
    with pytest.raises(ValueError, match="api_key and api_secret are required"):
        shopify_oauth.exchange_code(SHOP, "code", api_key=API_KEY, api_secret="")


def test_exchange_code_rejects_non_shopify_domain() -> None:
    with pytest.raises(ValueError, match=r"must end with \.myshopify\.com"):
        shopify_oauth.exchange_code("example.com", "code", API_KEY, API_SECRET)


# ── verify_webhook_hmac ────────────────────────────────────────────────


def _sign(data: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def test_verify_webhook_hmac_valid() -> None:
    body = b'{"id": 123, "event": "products/update"}'
    header = _sign(body, API_SECRET)
    assert shopify_oauth.verify_webhook_hmac(body, header, API_SECRET) is True


def test_verify_webhook_hmac_invalid_signature() -> None:
    body = b'{"id": 123}'
    header = _sign(b'{"id": 999}', API_SECRET)  # signed a different body
    assert shopify_oauth.verify_webhook_hmac(body, header, API_SECRET) is False


def test_verify_webhook_hmac_wrong_secret() -> None:
    body = b'{"id": 123}'
    header = _sign(body, "wrong-secret")
    assert shopify_oauth.verify_webhook_hmac(body, header, API_SECRET) is False


def test_verify_webhook_hmac_empty_header_returns_false() -> None:
    assert shopify_oauth.verify_webhook_hmac(b"{}", "", API_SECRET) is False


def test_verify_webhook_hmac_empty_secret_returns_false() -> None:
    body = b"{}"
    header = _sign(body, API_SECRET)
    assert shopify_oauth.verify_webhook_hmac(body, header, "") is False


def test_verify_webhook_hmac_tolerates_whitespace_in_header() -> None:
    body = b'{"id": 1}'
    header = _sign(body, API_SECRET)
    assert shopify_oauth.verify_webhook_hmac(body, f"  {header}  ", API_SECRET) is True
