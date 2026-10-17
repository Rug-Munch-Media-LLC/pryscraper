"""Peer-trust + SSRF DNS-pinning regressions (hardening 2026-10-17)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.routers.integrations import webhooks
from pry.core import middleware_auth
from pry.core.errors import InvalidRequestError
from pry.engine import url_guard
from pry.engine.url_guard import safe_get, validate_url


def _scope(peer: str, xff: str | None = None) -> dict:
    headers = [] if xff is None else [(b"x-forwarded-for", xff.encode())]
    return {"type": "http", "client": [peer, 1000], "headers": headers}


def _keyless(monkeypatch) -> None:
    monkeypatch.setattr(middleware_auth.settings, "api_key", "")
    monkeypatch.delenv("PRY_ALLOW_KEYLESS_LOOPBACK", raising=False)


def test_loopback_peer_with_untrusted_xff_is_unauthorised(monkeypatch):
    _keyless(monkeypatch)
    monkeypatch.setattr(middleware_auth, "_TRUSTED_PROXY_NETWORKS", ())
    assert middleware_auth.request_authorized(_scope("127.0.0.1", "203.0.113.9")) is False


def test_loopback_peer_via_trusted_proxy_with_public_xff_is_unauthorised(monkeypatch):
    _keyless(monkeypatch)
    monkeypatch.setattr(
        middleware_auth, "_TRUSTED_PROXY_NETWORKS", (ipaddress.ip_network("127.0.0.0/8"),)
    )
    assert middleware_auth.request_authorized(_scope("127.0.0.1", "203.0.113.9")) is False


def test_direct_loopback_still_works_in_dev(monkeypatch):
    _keyless(monkeypatch)
    monkeypatch.setattr(middleware_auth.settings, "environment", "dev")
    assert middleware_auth.request_authorized(_scope("127.0.0.1")) is True
    assert middleware_auth.request_authorized(_scope("testclient")) is True


def test_keyless_loopback_is_off_in_prod(monkeypatch):
    _keyless(monkeypatch)
    monkeypatch.setattr(middleware_auth.settings, "environment", "prod")
    assert middleware_auth.request_authorized(_scope("127.0.0.1")) is False


def test_trusted_proxy_takes_rightmost_public_hop(monkeypatch):
    monkeypatch.setattr(
        middleware_auth, "_TRUSTED_PROXY_NETWORKS", (ipaddress.ip_network("127.0.0.0/8"),)
    )
    chain = _scope("127.0.0.1", "198.51.100.7, 127.0.0.1")
    assert middleware_auth.resolve_client_ip(chain) == "198.51.100.7"
    # Malformed chain -> ambiguous identity -> unauthorised.
    assert middleware_auth.resolve_client_ip(_scope("127.0.0.1", "not-an-ip")) is None


def test_webhook_test_requires_auth(monkeypatch):
    monkeypatch.setattr(middleware_auth.settings, "api_key", "test-key")
    app = FastAPI()
    app.include_router(webhooks.router)
    resp = TestClient(app).post("/v1/webhooks/test", json={"url": "https://example.com/hook"})
    assert resp.status_code == 401


def test_dns_failure_fails_closed_with_4xx(monkeypatch):
    def boom(*_args, **_kwargs):
        raise socket.gaierror("name resolution disabled")

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", boom)
    with pytest.raises(InvalidRequestError) as exc:
        validate_url("https://rebind.example/")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_connect_target_is_the_validated_ip(monkeypatch):
    resolutions: list[str] = []

    def fake_getaddrinfo(host, port):
        resolutions.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)

    captured: dict = {}

    class FakeClient:
        async def get(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return httpx.Response(200, request=httpx.Request("GET", url), text="ok")

    resp = await safe_get(FakeClient(), "https://example.com/page")
    assert resp.status_code == 200
    assert urlparse(captured["url"]).hostname == "93.184.216.34"
    assert captured["kwargs"]["headers"]["Host"] == "example.com"
    assert captured["kwargs"]["extensions"]["sni_hostname"] == "example.com"
    assert len(resolutions) == 1  # one resolution, then connect to that exact IP
