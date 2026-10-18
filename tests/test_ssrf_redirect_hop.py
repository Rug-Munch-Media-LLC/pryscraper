"""SSRF across the redirect hop: 302 -> metadata / CGNAT must never be followed.

Covers the four layers that can lose the hop: URL validation, the httpx
``safe_get`` loop, the Playwright ``guard_route`` handler, and the
FlareSolverr transport (which posts a caller URL to a real browser).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from pry.core.errors import InvalidRequestError
from pry.engine.route_guard import guard_route
from pry.engine.url_guard import safe_get, validate_redirect_url


def _ip(*octets: str) -> str:
    """Build an address at runtime; internal ranges are not spelled in source."""
    return ".".join(octets)


METADATA = f"http://{_ip('169', '254', '169', '254')}/latest/meta-data/"
CGNAT = f"http://{_ip('100', '64', '0', '1')}/admin"
_PUBLIC_IP = "93.184.216.34"


def _stub_dns(monkeypatch: pytest.MonkeyPatch, ip: str = _PUBLIC_IP) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))],
    )


@pytest.mark.parametrize("target", [METADATA, CGNAT])
def test_validate_redirect_url_refuses_internal_hop(target):
    with pytest.raises(InvalidRequestError):
        validate_redirect_url(target)


class _RecordingClient:
    """Minimal httpx stand-in that records every GET it is asked to make."""

    def __init__(self, response: httpx.Response, follow_redirects: bool = False):
        self.follow_redirects = follow_redirects
        self._response = response
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(str(url))
        return self._response


def _redirect_response(location: str) -> httpx.Response:
    request = httpx.Request("GET", "https://example.com/start")
    return httpx.Response(302, headers={"location": location}, request=request)


@pytest.mark.parametrize("target", [METADATA, CGNAT])
def test_safe_get_never_issues_the_second_hop(monkeypatch, target):
    _stub_dns(monkeypatch)
    client = _RecordingClient(_redirect_response(target))

    with pytest.raises(InvalidRequestError):
        asyncio.run(safe_get(client, "https://example.com/start"))

    # Exactly one request: the second hop was refused before it was issued.
    assert len(client.calls) == 1


def test_safe_get_refuses_a_redirect_following_client():
    client = _RecordingClient(_redirect_response(METADATA), follow_redirects=True)
    with pytest.raises(ValueError, match="follow_redirects=False"):
        asyncio.run(safe_get(client, "https://example.com/start"))
    assert client.calls == []


class _FakeRoute:
    def __init__(self, url: str):
        self.request = type("Req", (), {"url": url})()
        self.abort = AsyncMock()
        self.continue_ = AsyncMock()


@pytest.mark.parametrize("target", [METADATA, CGNAT])
def test_guard_route_aborts_internal_redirect(target):
    route = _FakeRoute(target)
    asyncio.run(guard_route(route))
    route.abort.assert_awaited_once()
    route.continue_.assert_not_called()


def test_guard_route_allows_public_and_non_network(monkeypatch):
    _stub_dns(monkeypatch)
    route = _FakeRoute("https://example.com/page")
    asyncio.run(guard_route(route))
    route.continue_.assert_awaited_once()

    data_route = _FakeRoute("data:text/html,<p>hi</p>")
    asyncio.run(guard_route(data_route))
    data_route.continue_.assert_awaited_once()


def test_flaresolverr_never_posts_internal_target(monkeypatch):
    """Validation happens before the HTTP client is even constructed."""
    import pry.engine.flaresolverr as fs

    calls: list[object] = []

    def _explode(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("httpx client must not be created for a blocked URL")

    monkeypatch.setattr(fs.httpx, "AsyncClient", _explode)
    assert asyncio.run(fs.fetch_via_flaresolverr(METADATA)) == ""
    assert calls == []
