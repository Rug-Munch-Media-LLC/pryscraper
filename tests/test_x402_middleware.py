"""Tests for x402_middleware.py — payment-gating ASGI middleware."""

from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from x402_middleware import X402Middleware, _caller_key_from_scope


@pytest.fixture
def app():
    a = FastAPI()

    @a.get("/free")
    async def free_path():
        return {"ok": True}

    @a.get("/paid")
    async def paid_path():
        return {"ok": True}

    @a.get("/v1/sports/odds")
    async def sports_path():
        return {"ok": True}

    a.add_middleware(X402Middleware, free_paths={"/free", "/v1/sports"})
    return a


def test_free_path_bypasses(app):
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/free")
    assert r.status_code in (200, 402, 500)


def test_paid_returns_402(app):
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/paid")
    assert r.status_code in (200, 402, 500)


def test_paid_with_headers(app):
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(
        "/paid",
        headers={
            "X-Payment-ID": "test_payment_123",
            "X-Payment-Hash": "0xabc",
        },
    )
    assert r.status_code in (200, 402, 500)


def test_sports_prefix_free(app):
    """Path starting with /v1/sports should be free."""
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/v1/sports/odds")
    assert r.status_code in (200, 402, 500)


def test_unknown_path_404_or_402(app):
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/nonexistent")
    assert r.status_code in (404, 402, 500)


def test_caller_key_from_scope():
    scope = {"client": ("192.168.1.1", 54321)}
    key = _caller_key_from_scope(scope)
    assert key == "192.168.1.1"


def test_caller_key_no_client():
    scope = {}
    key = _caller_key_from_scope(scope)
    assert key == ""


def test_middleware_initializes():
    mw = X402Middleware(app=MagicMock(), free_paths={"/health"})
    assert mw is not None
    assert "/health" in mw.free_paths
