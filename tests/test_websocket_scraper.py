# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for WebSocket/SSE SSRF host validation.

``websocket_scraper.validate_websocket_url`` is the scheme-aware guard for
``ws://``/``wss://`` URLs (``url_guard.validate_url`` only accepts http/https),
and ``scrape_websocket`` / ``scrape_sse`` must gate their targets before any
connection is attempted.
"""

from __future__ import annotations

import socket
import sys
import types
from unittest.mock import MagicMock

import pytest

from pry.core.errors import InvalidRequestError
from pry.engine import url_guard
from pry.engine.websocket_scraper import WebSocketScraper, validate_websocket_url


class TestValidateWebsocketURL:
    def test_accepts_public_wss(self) -> None:
        result = validate_websocket_url("wss://echo.websocket.org/")
        assert result == "wss://echo.websocket.org/"

    def test_accepts_public_ws_with_path(self) -> None:
        result = validate_websocket_url("ws://example.com/socket.io/?EIO=4")
        assert result == "ws://example.com/socket.io/?EIO=4"

    def test_rejects_empty_url(self) -> None:
        with pytest.raises(InvalidRequestError):
            validate_websocket_url("")

    def test_rejects_http_scheme(self) -> None:
        with pytest.raises(InvalidRequestError):
            validate_websocket_url("http://example.com/socket")

    def test_rejects_https_scheme(self) -> None:
        with pytest.raises(InvalidRequestError):
            validate_websocket_url("https://example.com/socket")

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(InvalidRequestError):
            validate_websocket_url("ftp://example.com/socket")

    def test_rejects_empty_hostname(self) -> None:
        with pytest.raises(InvalidRequestError):
            validate_websocket_url("ws:///socket")

    def test_rejects_embedded_credentials(self) -> None:
        with pytest.raises(InvalidRequestError):
            validate_websocket_url("ws://user:pass@example.com/socket")

    # ── Private / reserved IP literals ───────────────────────────

    @pytest.mark.parametrize(
        "url",
        [
            "ws://127.0.0.1/",
            "ws://127.0.0.1:8080/socket",
            "wss://[::1]/",
            "ws://10.0.0.1/",
            "ws://172.16.0.1/",
            "ws://192.168.1.1/",
            "ws://100.64.0.1/",  # RFC 6598 CGNAT
            "ws://169.254.169.254/latest/meta-data/",  # cloud metadata
            "ws://0.0.0.0/",
        ],
    )
    def test_rejects_private_metadata_loopback_ips(self, url: str) -> None:
        with pytest.raises(InvalidRequestError):
            validate_websocket_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "ws://[fe80::1]/",  # IPv6 link-local
            "ws://[fc00::1]/",  # IPv6 ULA
        ],
    )
    def test_rejects_private_ipv6(self, url: str) -> None:
        with pytest.raises(InvalidRequestError):
            validate_websocket_url(url)

    # ── Internal hostnames ───────────────────────────────────────

    @pytest.mark.parametrize(
        "url",
        [
            "ws://localhost/socket",
            "ws://localhost.localdomain/socket",
            "ws://internal.corp/socket",
            "ws://kubernetes.default.svc.cluster.local/socket",
            "ws://metadata.google.internal/socket",
            "ws://docker/container",
        ],
    )
    def test_rejects_internal_hostnames(self, url: str) -> None:
        with pytest.raises(InvalidRequestError):
            validate_websocket_url(url)

    # ── DNS rebinding ────────────────────────────────────────────

    def test_dns_resolution_blocks_private_ip_by_default(self, monkeypatch) -> None:
        """A public-looking hostname that resolves to a private IP must be
        rejected (mirrors url_guard's resolve_dns=True default)."""

        def fake_getaddrinfo(host, port):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80)),
            ]

        # DNS resolution now lives in url_guard._validate_host (shared helper).
        monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(InvalidRequestError):
            validate_websocket_url("ws://public.example.com/socket")

    def test_dns_resolution_blocks_metadata_ip_by_default(self, monkeypatch) -> None:
        def fake_getaddrinfo(host, port):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80)),
            ]

        monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(InvalidRequestError):
            validate_websocket_url("ws://public.example.com/socket")

    def test_resolve_dns_false_skips_dns_check(self, monkeypatch) -> None:
        def fake_getaddrinfo(host, port):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80)),
            ]

        monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)
        result = validate_websocket_url("ws://public.example.com/socket", resolve_dns=False)
        assert result == "ws://public.example.com/socket"


class TestScrapeWebsocketGating:
    @pytest.mark.asyncio
    async def test_private_url_blocked_before_connect(self, monkeypatch) -> None:
        """A loopback target must be rejected without ever dialing the socket."""
        connect_called = False

        async def fake_connect(*args, **kwargs) -> None:
            nonlocal connect_called
            connect_called = True
            raise AssertionError("must not connect to a private target")

        fake_ws = types.ModuleType("websockets")
        fake_ws.connect = fake_connect  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "websockets", fake_ws)

        with pytest.raises(InvalidRequestError):
            await WebSocketScraper().scrape_websocket("ws://127.0.0.1/socket")

        assert connect_called is False

    @pytest.mark.asyncio
    async def test_metadata_url_blocked_before_connect(self, monkeypatch) -> None:
        connect_called = False

        async def fake_connect(*args, **kwargs) -> None:
            nonlocal connect_called
            connect_called = True
            raise AssertionError("must not connect to metadata endpoint")

        fake_ws = types.ModuleType("websockets")
        fake_ws.connect = fake_connect  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "websockets", fake_ws)

        with pytest.raises(InvalidRequestError):
            await WebSocketScraper().scrape_websocket("ws://169.254.169.254/")

        assert connect_called is False

    @pytest.mark.asyncio
    async def test_internal_hostname_blocked_before_connect(self, monkeypatch) -> None:
        connect_called = False

        async def fake_connect(*args, **kwargs) -> None:
            nonlocal connect_called
            connect_called = True
            raise AssertionError("must not connect to internal host")

        fake_ws = types.ModuleType("websockets")
        fake_ws.connect = fake_connect  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "websockets", fake_ws)

        with pytest.raises(InvalidRequestError):
            await WebSocketScraper().scrape_websocket("ws://internal.corp/socket")

        assert connect_called is False


class TestScrapeSseGating:
    @pytest.mark.asyncio
    async def test_private_url_rejected(self, monkeypatch) -> None:
        get_client_called = False

        async def fake_get_client():
            nonlocal get_client_called
            get_client_called = True
            raise AssertionError("must not acquire client for private target")

        import pry.api.client as client_module

        monkeypatch.setattr(client_module, "get_client", fake_get_client)
        with pytest.raises(InvalidRequestError):
            await WebSocketScraper().scrape_sse("http://169.254.169.254/events")

        assert get_client_called is False

    @pytest.mark.asyncio
    async def test_loopback_url_rejected(self, monkeypatch) -> None:
        async def fake_get_client():
            raise AssertionError("must not acquire client")

        import pry.api.client as client_module

        monkeypatch.setattr(client_module, "get_client", fake_get_client)
        with pytest.raises(InvalidRequestError):
            await WebSocketScraper().scrape_sse("http://127.0.0.1:8080/events")

    @pytest.mark.asyncio
    async def test_non_http_scheme_rejected(self, monkeypatch) -> None:
        """SSE endpoints are http/https only — ws:// must be rejected."""

        async def fake_get_client():
            raise AssertionError("must not acquire client")

        import pry.api.client as client_module

        monkeypatch.setattr(client_module, "get_client", fake_get_client)
        with pytest.raises(InvalidRequestError):
            await WebSocketScraper().scrape_sse("ws://example.com/events")

    @pytest.mark.asyncio
    async def test_public_url_streams_events(self, monkeypatch) -> None:
        """Happy path: a public SSE endpoint is streamed (guarded, not blocked)."""

        class FakeStreamResponse:
            def __init__(self) -> None:
                self.lines = [
                    "event: message",
                    'data: {"hello": "world"}',
                    "extra: trigger-flush",
                ]

            async def __aenter__(self) -> FakeStreamResponse:
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

            async def aiter_lines(self):
                for line in self.lines:
                    yield line

        fake_client = MagicMock()
        fake_client.stream.return_value = FakeStreamResponse()

        async def fake_get_client():
            return fake_client

        import pry.api.client as client_module

        monkeypatch.setattr(client_module, "get_client", fake_get_client)
        result = await WebSocketScraper(timeout=5).scrape_sse("https://example.com/events")

        assert result["success"] is True
        assert result["count"] == 1
        assert result["events"][0]["data"] == {"hello": "world"}
