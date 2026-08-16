"""Tests for the standalone Tor fallback helper (tor_fallback.py).

All tests mock ``aiohttp_socks.ProxyConnector`` and the aiohttp session —
no live Tor daemon is required. The lazy imports inside
``fetch_via_tor`` mean tests must patch ``sys.modules`` / module
attributes rather than the ``tor_fallback`` namespace directly.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

import tor_fallback
from tor_fallback import (
    DEFAULT_TOR_HOST,
    DEFAULT_TOR_PORT,
    fetch_via_tor,
    tor_available,
    tor_status,
)


def _fake_session(status: int = 200, text: str = "<html>ok</html>") -> MagicMock:
    """Build a mocked aiohttp.ClientSession class.

    ``session.get(url)`` is an async context manager whose ``__aenter__``
    yields a mocked response with ``status`` / ``text()``.
    """
    resp = AsyncMock()
    resp.status = status
    resp.text.return_value = text

    get_cm = AsyncMock()
    get_cm.__aenter__.return_value = resp

    # Plain MagicMock so session.get(url) returns get_cm directly (aiohttp
    # returns a request context manager, not a coroutine).
    session = MagicMock()
    session.get.return_value = get_cm

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session

    client_session_cls = MagicMock(return_value=session_cm)
    return client_session_cls


class TestFetchViaTor:
    """fetch_via_tor: success, graceful None, and never-raise contract."""

    @pytest.mark.anyio
    async def test_returns_html_on_success(self) -> None:
        html = "<html><body>via tor</body></html>"
        fake_connector = MagicMock()
        with (
            patch("aiohttp_socks.ProxyConnector", fake_connector),
            patch("aiohttp.ClientSession", _fake_session(status=200, text=html)),
        ):
            result = await fetch_via_tor("https://example.com/page")
        assert result == html

    @pytest.mark.anyio
    async def test_passes_host_port_rdns_to_connector(self) -> None:
        fake_connector = MagicMock()
        with (
            patch("aiohttp_socks.ProxyConnector", fake_connector),
            patch("aiohttp.ClientSession", _fake_session()),
        ):
            await fetch_via_tor("https://example.com", tor_host="127.0.0.9", tor_port=9999)
        fake_connector.assert_called_once_with(host="127.0.0.9", port=9999, rdns=True)

    @pytest.mark.anyio
    async def test_non_200_returns_none(self) -> None:
        with (
            patch("aiohttp_socks.ProxyConnector", MagicMock()),
            patch("aiohttp.ClientSession", _fake_session(status=503)),
        ):
            result = await fetch_via_tor("https://example.com")
        assert result is None

    @pytest.mark.anyio
    async def test_missing_dependency_returns_none(self) -> None:
        """aiohttp_socks absent -> ImportError inside fetch -> graceful None."""
        with patch.dict(sys.modules, {"aiohttp_socks": None}):
            result = await fetch_via_tor("https://example.com")
        assert result is None

    @pytest.mark.anyio
    async def test_connection_error_returns_none(self) -> None:
        """SOCKS port unreachable: connector raises OSError (SocksConnectionError)."""

        def _refused(*args: object, **kwargs: object) -> None:
            raise ConnectionRefusedError("tor not running")

        with (
            patch("aiohttp_socks.ProxyConnector", _refused),
            patch("aiohttp.ClientSession", _fake_session()),
        ):
            result = await fetch_via_tor("https://example.com")
        assert result is None

    @pytest.mark.anyio
    async def test_session_get_error_returns_none(self) -> None:
        """aiohttp ClientError from session.get -> graceful None."""
        client = _fake_session()
        client.return_value.__aenter__.return_value.get.side_effect = aiohttp.ClientConnectionError(
            "proxy refused"
        )
        with (
            patch("aiohttp_socks.ProxyConnector", MagicMock()),
            patch("aiohttp.ClientSession", client),
        ):
            result = await fetch_via_tor("https://example.com")
        assert result is None

    @pytest.mark.anyio
    async def test_timeout_returns_none(self) -> None:
        """asyncio.TimeoutError from session.get -> graceful None."""
        client = _fake_session()
        client.return_value.__aenter__.return_value.get.side_effect = TimeoutError(
            "socks timed out"
        )
        with (
            patch("aiohttp_socks.ProxyConnector", MagicMock()),
            patch("aiohttp.ClientSession", client),
        ):
            result = await fetch_via_tor("https://example.com", timeout=1.0)
        assert result is None

    @pytest.mark.anyio
    async def test_socks_proxy_error_returns_none(self) -> None:
        """aiohttp_socks.ProxyError (plain Exception, not OSError) -> graceful None."""
        from aiohttp_socks import ProxyError

        client = _fake_session()
        client.return_value.__aenter__.return_value.get.side_effect = ProxyError(
            "SOCKS handshake failed"
        )
        with (
            patch("aiohttp_socks.ProxyConnector", MagicMock()),
            patch("aiohttp.ClientSession", client),
        ):
            result = await fetch_via_tor("https://example.com")
        assert result is None


class TestTorAvailable:
    """tor_available(): dependency + port reachability detection."""

    def test_true_when_installed_and_reachable(self) -> None:
        with (
            patch("tor_fallback._aiohttp_socks_installed", return_value=True),
            patch("tor_fallback._socks_port_reachable", return_value=True),
        ):
            assert tor_available() is True

    def test_false_when_dependency_missing(self) -> None:
        with (
            patch("tor_fallback._aiohttp_socks_installed", return_value=False),
            patch("tor_fallback._socks_port_reachable", return_value=True),
        ):
            assert tor_available() is False

    def test_false_when_port_closed(self) -> None:
        with (
            patch("tor_fallback._aiohttp_socks_installed", return_value=True),
            patch("tor_fallback._socks_port_reachable", return_value=False),
        ):
            assert tor_available() is False

    def test_default_host_port(self) -> None:
        assert tor_fallback.DEFAULT_TOR_HOST == DEFAULT_TOR_HOST == "127.0.0.1"
        assert tor_fallback.DEFAULT_TOR_PORT == DEFAULT_TOR_PORT == 9050

    def test_detects_installed_package(self) -> None:
        """Real find_spec against the installed aiohttp-socks."""
        assert tor_fallback._aiohttp_socks_installed() is True

    def test_probe_closed_port_returns_false(self) -> None:
        """Real TCP probe against a port that is not listening."""
        # Use an ephemeral port that is very unlikely to be listening.
        assert tor_fallback._socks_port_reachable("127.0.0.1", 1) is False


class TestTorStatus:
    """tor_status(): monitoring dict."""

    def test_shape_when_available(self) -> None:
        with (
            patch("tor_fallback._aiohttp_socks_installed", return_value=True),
            patch("tor_fallback._socks_port_reachable", return_value=True),
        ):
            status = tor_status()
        assert status == {
            "available": True,
            "host": DEFAULT_TOR_HOST,
            "port": DEFAULT_TOR_PORT,
            "reachable": True,
        }

    def test_shape_when_unavailable(self) -> None:
        with (
            patch("tor_fallback._aiohttp_socks_installed", return_value=False),
            patch("tor_fallback._socks_port_reachable", return_value=False),
        ):
            status = tor_status()
        assert status["available"] is False
        assert status["reachable"] is False
        assert status["port"] == DEFAULT_TOR_PORT
