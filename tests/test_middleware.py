"""Tests for middleware.py — ASGI auth, rate limiting, IP resolution."""

from __future__ import annotations

import ipaddress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.routing import Mount, Route

from pry.core.middleware import (
    PryHttpMiddleware,
    _is_trusted_proxy,
    _parse_trusted_proxy,
    _path_exists,
    _resolve_client_ip,
    is_loopback_client,
    request_authorized,
)

# ---------------------------------------------------------------------------
# _path_exists
# ---------------------------------------------------------------------------


def _make_app(routes=None, mounts=None):
    app = MagicMock()
    app.routes = (routes or []) + (mounts or [])
    return app


def test_path_exists_exact_route():
    app = _make_app(routes=[Route("/test", lambda: None)])
    assert _path_exists("/test", app) is True


def test_path_exists_no_match():
    app = _make_app(routes=[Route("/test", lambda: None)])
    assert _path_exists("/other", app) is False


def test_path_exists_no_routes():
    app = _make_app(routes=[])
    assert _path_exists("/anything", app) is False


def test_path_exists_with_param():
    app = _make_app(routes=[Route("/items/{item_id}", lambda: None)])
    assert _path_exists("/items/42", app) is True


def test_path_exists_with_param_no_match():
    app = _make_app(routes=[Route("/items/{item_id}", lambda: None)])
    assert _path_exists("/other/42", app) is False


def test_path_exists_mount_prefix():
    sub = _make_app(routes=[Route("/list", lambda: None)])
    app = _make_app(mounts=[Mount("/api", app=sub)])
    assert _path_exists("/api/list", app) is True


def test_path_exists_mount_catch_all():
    sub = _make_app(routes=[])
    app = _make_app(mounts=[Mount("/api", app=sub)])
    assert _path_exists("/api/anything", app) is True


def test_path_exists_root_mount():
    sub = _make_app(routes=[Route("/health", lambda: None)])
    app = _make_app(mounts=[Mount("/", app=sub)])
    assert _path_exists("/health", app) is True


def test_path_exists_empty_mount_no_sub():
    app = _make_app(mounts=[Mount("", app=MagicMock(routes=None))])
    assert _path_exists("/anything", app) is False


# ---------------------------------------------------------------------------
# is_loopback_client
# ---------------------------------------------------------------------------


def test_is_loopback_ipv4():
    assert is_loopback_client("127.0.0.1") is True


def test_is_loopback_ipv6():
    assert is_loopback_client("::1") is True


def test_is_loopback_mapped():
    assert is_loopback_client("::ffff:127.0.0.1") is True


def test_is_loopback_testclient():
    assert is_loopback_client("testclient") is True


def test_is_loopback_range():
    assert is_loopback_client("127.0.0.2") is True
    assert is_loopback_client("127.99.99.99") is True


def test_is_not_loopback():
    assert is_loopback_client("10.0.0.1") is False
    assert is_loopback_client("192.168.1.1") is False


def test_is_loopback_empty():
    assert is_loopback_client("") is False


def test_is_loopback_unknown():
    assert is_loopback_client("unknown") is False


# ---------------------------------------------------------------------------
# request_authorized
# ---------------------------------------------------------------------------


def test_auth_with_key_valid_bearer():
    with patch("pry.core.middleware.settings.api_key", "test-key-123"):
        scope = {"headers": [(b"authorization", b"Bearer test-key-123")], "client": ["10.0.0.1", 0]}
        assert request_authorized(scope) is True


def test_auth_with_key_no_auth_header():
    with patch("pry.core.middleware.settings.api_key", "test-key-123"):
        scope = {"headers": [], "client": ["10.0.0.1", 0]}
        assert request_authorized(scope) is False


def test_auth_with_key_wrong_bearer():
    with patch("pry.core.middleware.settings.api_key", "test-key-123"):
        scope = {"headers": [(b"authorization", b"Bearer wrong-key")], "client": ["10.0.0.1", 0]}
        assert request_authorized(scope) is False


def test_auth_no_key_loopback():
    with patch("pry.core.middleware.settings.api_key", ""):
        scope = {"client": ["127.0.0.1", 0]}
        assert request_authorized(scope) is True


def test_auth_no_key_remote():
    with patch("pry.core.middleware.settings.api_key", ""):
        scope = {"client": ["10.0.0.1", 0]}
        assert request_authorized(scope) is False


def test_auth_no_key_no_client():
    with patch("pry.core.middleware.settings.api_key", ""):
        scope = {}
        assert request_authorized(scope) is False


# ---------------------------------------------------------------------------
# _parse_trusted_proxy
# ---------------------------------------------------------------------------


def test_parse_trusted_proxy_ipv4():
    net = _parse_trusted_proxy("10.0.0.0/8")
    assert net is not None
    assert net.prefixlen == 8


def test_parse_trusted_proxy_single_ip():
    net = _parse_trusted_proxy("192.168.1.1")
    assert net is not None
    assert net.prefixlen == 32
    assert str(net.network_address) == "192.168.1.1"


def test_parse_trusted_proxy_invalid():
    assert _parse_trusted_proxy("not-an-ip") is None


def test_parse_trusted_proxy_empty():
    assert _parse_trusted_proxy("") is None


# ---------------------------------------------------------------------------
# _is_trusted_proxy
# ---------------------------------------------------------------------------


def test_is_trusted_proxy_in_network():
    networks = (ipaddress.ip_network("10.0.0.0/8"),)
    with patch("pry.core.middleware._TRUSTED_PROXY_NETWORKS", networks):
        assert _is_trusted_proxy("10.0.0.5") is True


def test_is_trusted_proxy_not_in_network():
    networks = (ipaddress.ip_network("10.0.0.0/8"),)
    with patch("pry.core.middleware._TRUSTED_PROXY_NETWORKS", networks):
        assert _is_trusted_proxy("192.168.1.1") is False


def test_is_trusted_proxy_empty():
    with patch("pry.core.middleware._TRUSTED_PROXY_NETWORKS", ()):
        assert _is_trusted_proxy("10.0.0.5") is False


def test_is_trusted_proxy_empty_ip():
    with patch("pry.core.middleware._TRUSTED_PROXY_NETWORKS", ()):
        assert _is_trusted_proxy("") is False


def test_is_trusted_proxy_unknown():
    with patch("pry.core.middleware._TRUSTED_PROXY_NETWORKS", ()):
        assert _is_trusted_proxy("unknown") is False


def test_is_trusted_proxy_invalid_ip():
    with patch("pry.core.middleware._TRUSTED_PROXY_NETWORKS", ()):
        assert _is_trusted_proxy("bad-ip") is False


# ---------------------------------------------------------------------------
# _resolve_client_ip
# ---------------------------------------------------------------------------


def test_resolve_client_ip_peer():
    scope = {"client": ["10.0.0.1", 0]}
    with patch("pry.core.middleware._is_trusted_proxy", return_value=False):
        assert _resolve_client_ip(scope) == "10.0.0.1"


def test_resolve_client_ip_loopback_xff():
    scope = {"client": ["127.0.0.1", 0], "headers": [(b"x-forwarded-for", b"203.0.113.5")]}
    assert _resolve_client_ip(scope) == "203.0.113.5"


def test_resolve_client_ip_trusted_proxy_xff():
    scope = {"client": ["10.0.0.5", 0], "headers": [(b"x-forwarded-for", b"203.0.113.5, 10.0.0.1")]}
    with patch("pry.core.middleware._is_trusted_proxy", return_value=True):
        assert _resolve_client_ip(scope) == "203.0.113.5"


def test_resolve_client_ip_no_client():
    assert _resolve_client_ip({}) == "unknown"


def test_resolve_client_ip_unknown_peer():
    scope = {"client": ["unknown", 0]}
    assert _resolve_client_ip(scope) == "unknown"


def test_resolve_client_ip_empty_peer():
    scope = {"client": ["", 0]}
    assert _resolve_client_ip(scope) == "unknown"


def test_resolve_client_ip_xff_stripped():
    scope = {"client": ["127.0.0.1", 0], "headers": [(b"x-forwarded-for", b"  8.8.8.8  ")]}
    assert _resolve_client_ip(scope) == "8.8.8.8"


def test_resolve_client_ip_xff_empty():
    scope = {"client": ["127.0.0.1", 0], "headers": [(b"x-forwarded-for", b"")]}
    assert _resolve_client_ip(scope) == "127.0.0.1"


# ---------------------------------------------------------------------------
# PryHttpMiddleware._get_header
# ---------------------------------------------------------------------------


def test_get_header_exists():
    scope = {"headers": [(b"content-type", b"application/json")]}
    assert PryHttpMiddleware._get_header(scope, b"content-type") == "application/json"


def test_get_header_case_insensitive():
    scope = {"headers": [(b"Content-Type", b"text/html")]}
    assert PryHttpMiddleware._get_header(scope, b"content-type") == "text/html"


def test_get_header_missing():
    assert PryHttpMiddleware._get_header({}, b"x-missing") == ""


def test_get_header_empty_headers():
    scope = {"headers": []}
    assert PryHttpMiddleware._get_header(scope, b"anything") == ""


# ---------------------------------------------------------------------------
# PryHttpMiddleware.__call__ — ASGI integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_non_http_skips():
    """Non-HTTP scope (e.g. websocket) should pass through."""
    app = AsyncMock()
    mw = PryHttpMiddleware(app)
    scope = {"type": "websocket", "path": "/ws", "method": "GET"}
    await mw(scope, None, None)
    app.assert_awaited_once_with(scope, None, None)


@pytest.mark.asyncio
async def test_middleware_options_passthrough():
    """OPTIONS requests should pass through without auth."""
    app = AsyncMock()
    mw = PryHttpMiddleware(app)
    scope = {
        "type": "http",
        "method": "OPTIONS",
        "path": "/test",
        "headers": [],
        "client": ["10.0.0.1", 0],
    }
    await mw(scope, None, None)
    app.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_unauthorized():
    """Non-loopback without API key should get 401."""
    app = AsyncMock()
    mw = PryHttpMiddleware(app)

    sent_responses = []

    async def send(msg):
        sent_responses.append(msg)

    with patch("pry.core.middleware.settings.api_key", ""):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
            "client": ["10.0.0.1", 0],
        }
        await mw(scope, None, send)

    assert len(sent_responses) >= 1
    assert sent_responses[0]["status"] == 401


@pytest.mark.asyncio
async def test_middleware_public_path_skips_auth():
    """Public paths like /health should skip auth check."""
    app = AsyncMock()
    mw = PryHttpMiddleware(app)

    with patch("pry.core.middleware.settings.api_key", "some-key"):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": [(b"authorization", b"Bearer wrong")],
            "client": ["10.0.0.1", 0],
        }
        await mw(scope, None, None)
        app.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/hosting/signup"),
        ("POST", "/v1/hosting/signup/inv_abc123/confirm"),
        ("GET", "/v1/hosting/checkout/inv_abc123"),
        ("GET", "/v1/hosting/portal"),
    ],
)
async def test_middleware_hosting_human_rail_is_pre_auth(method, path):
    """The human payment rail must be reachable WITHOUT an API key.

    Regression: a prospective customer has no key yet — the payment IS the
    auth. signup + confirm were missing from _AUTH_PUBLIC_PATHS, so the live
    container 401'd the first step of the human rail (checkout/portal were
    fixed earlier; signup was missed).
    """
    app = AsyncMock()
    mw = PryHttpMiddleware(app)

    with patch("pry.core.middleware.settings.api_key", "some-key"):
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],  # no Authorization header at all
            "client": ["10.0.0.1", 0],
        }
        await mw(scope, None, None)
        app.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_unknown_path_passes_through():
    """Unknown paths should be passed to the app (404 handler)."""
    app = AsyncMock()
    mw = PryHttpMiddleware(app)

    with patch("pry.core.middleware.settings.api_key", ""):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/nonexistent",
            "headers": [],
            "client": ["127.0.0.1", 0],
        }
        await mw(scope, None, None)
        app.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_authenticated_request():
    """Valid API key should pass through."""
    app = AsyncMock()
    mw = PryHttpMiddleware(app)

    with (
        patch("pry.core.middleware.settings.api_key", "test-key"),
        patch("pry.core.middleware._path_exists", return_value=True),
    ):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/scrape",
            "headers": [(b"authorization", b"Bearer test-key")],
            "client": ["10.0.0.1", 0],
        }
        await mw(scope, None, None)
        app.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_401_response_format():
    """401 responses should have proper JSON body."""
    app = AsyncMock()
    mw = PryHttpMiddleware(app)

    sent = []

    async def send(msg):
        sent.append(msg)

    def fake_receive():
        return {}

    with patch("pry.core.middleware.settings.api_key", ""):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
            "client": ["10.0.0.1", 0],
        }
        await mw(scope, fake_receive, send)

    assert len(sent) >= 1
    start = sent[0]
    assert start["status"] == 401
    assert b"x-request-id" in dict(start.get("headers", []))
