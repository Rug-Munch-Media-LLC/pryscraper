"""Tests for cli.py — Pry command-line interface."""

from __future__ import annotations
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx


def _mock_api(url: str) -> str:
    """Mock the API URL."""
    return url


def test_api_default():
    from cli import _api

    with patch.dict("os.environ", clear=True):
        assert _api() == "http://localhost:8005"


def test_api_from_env():
    from cli import _api

    with patch.dict("os.environ", {"PRY_URL": "http://custom:9000"}):
        assert _api() == "http://custom:9000"


@respx.mock
def test_req_get():
    from cli import _req

    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.get(f"{api_url}/v1/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        result = _req("GET", "/v1/health")
        assert result["status"] == "ok"


@respx.mock
def test_req_post():
    from cli import _req

    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.post(f"{api_url}/v1/scrape").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        result = _req("POST", "/v1/scrape", {"url": "http://example.com"})
        assert result["success"] is True


def test_req_connect_error():
    from cli import _req

    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        with pytest.raises(SystemExit):
            _req("GET", "/v1/health")


@respx.mock
def test_req_http_429():
    from cli import _req

    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.get(f"{api_url}/v1/health").mock(
            return_value=httpx.Response(429, text="Rate limited")
        )
        with pytest.raises(SystemExit):
            _req("GET", "/v1/health")


@respx.mock
def test_req_http_500():
    from cli import _req

    api_url = "http://localhost:8005"
    with patch.dict("os.environ", {"PRY_URL": api_url}):
        respx.get(f"{api_url}/v1/health").mock(
            return_value=httpx.Response(500, text="Server Error")
        )
        with pytest.raises(SystemExit):
            _req("GET", "/v1/health")


def test_print_usage():
    from cli import _print_usage

    _print_usage()


def test_version():
    from cli import VERSION

    assert VERSION == "3.0.0"


def test_version_constants():
    from cli import NC, RED, GREEN, YELLOW, CYAN, BOLD

    assert NC == "\033[0m"
    assert BOLD.startswith("\033")


# ── Command functions (test they execute without crash) ──


def test_main_imports():
    """CLI module imports cleanly."""
    import cli

    assert cli.__doc__ is not None
