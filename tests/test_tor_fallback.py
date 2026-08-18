# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for tor_fallback.py — Tor SOCKS5 proxy fallback for IP rotation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tor_fallback import (
    DEFAULT_TOR_HOST,
    DEFAULT_TOR_PORT,
    DEFAULT_TOR_TIMEOUT,
    _aiohttp_socks_installed,
    _socks_port_reachable,
    tor_available,
    tor_status,
)


def test_default_host():
    assert DEFAULT_TOR_HOST == "127.0.0.1"


def test_default_port():
    assert DEFAULT_TOR_PORT == 9050


def test_default_timeout():
    assert DEFAULT_TOR_TIMEOUT == 30.0


@patch.dict("sys.modules", {"aiohttp_socks": None}, clear=False)
def test_aiohttp_socks_not_installed():
    assert _aiohttp_socks_installed() is False


def test_aiohttp_socks_is_installed():
    """In the CI/test venv aiohttp_socks may or may not be present."""
    result = _aiohttp_socks_installed()
    assert isinstance(result, bool)


@patch("tor_fallback._aiohttp_socks_installed", return_value=True)
@patch("tor_fallback._socks_port_reachable", return_value=True)
def test_tor_available_true(mock_reach, mock_install):
    assert tor_available() is True


@patch("tor_fallback._aiohttp_socks_installed", return_value=False)
def test_tor_available_false_missing_dep(mock_install):
    assert tor_available() is False


@patch("tor_fallback._aiohttp_socks_installed", return_value=True)
@patch("tor_fallback._socks_port_reachable", return_value=True)
def test_tor_status_returns_info(mock_reach, mock_install):
    status = tor_status()
    assert "available" in status
    assert "host" in status
    assert "port" in status
    assert status["host"] == DEFAULT_TOR_HOST


@pytest.mark.skip(reason="fetch_via_tor needs aiohttp environment; tested via integration")
def test_fetch_via_tor_contract():
    """fetch_via_tor returns None when aiohttp_socks is missing."""


def test_socks_port_reachable():
    """Test that _socks_port_reachable returns a bool without exceptions."""
    result = _socks_port_reachable("127.0.0.1", 9050)
    assert isinstance(result, bool)


@patch("tor_fallback.socket.create_connection")
def test_socks_port_reachable_true(mock_create):
    mock_create.return_value.__enter__.return_value = MagicMock()
    assert _socks_port_reachable("127.0.0.1", 9050) is True


@patch("tor_fallback.socket.create_connection")
def test_socks_port_reachable_false(mock_create):
    mock_create.side_effect = OSError("refused")
    assert _socks_port_reachable("127.0.0.1", 9050) is False


def test_tor_proxy_chain_from_settings():
    from settings import settings

    original = settings.tor_enabled
    try:
        settings.tor_enabled = True
        chain = settings.resolved_proxy_chain
        assert any("socks5" in p for p in chain)
    finally:
        settings.tor_enabled = original
