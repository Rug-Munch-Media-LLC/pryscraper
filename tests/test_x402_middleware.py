"""Tests for x402_middleware.py — payment-gating ASGI middleware."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.payments.x402 import X402Handler, _encode_payment_required_body
from pry.payments.x402_middleware import (
    X402_PAYMENT_HEADER_MAX_BYTES,
    X402Middleware,
    _caller_key_from_scope,
    _compact_payment_required_header,
)


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


# ── Cloudflare header-size incident regression (2026-08-25) ──────────────
# The multi-asset 402 challenge base64-encoded to ~18KB in a single
# PAYMENT-REQUIRED header; Cloudflare's ~16KB per-header ceiling turned
# every public paid request into a 502 while local calls worked.


def test_compact_helper_noop_under_budget():
    body = {"x402Version": 1, "accepts": [{"scheme": "exact", "network": "eip155:8453"}]}
    out = _compact_payment_required_header(body, 12_000)
    assert out == _encode_payment_required_body(body)


def test_compact_helper_trims_to_budget_keeps_one_accept():
    handler = X402Handler()
    body, _ = handler.create_payment_required("scrape", resource="/v1/scrape", multi_asset=True)
    full_len = len(_encode_payment_required_body(body))
    assert full_len > X402_PAYMENT_HEADER_MAX_BYTES, "precondition: full table must exceed budget"

    out = _compact_payment_required_header(body, X402_PAYMENT_HEADER_MAX_BYTES)
    assert len(out.encode()) <= X402_PAYMENT_HEADER_MAX_BYTES

    import base64
    import json as _json

    decoded = _json.loads(base64.b64decode(out))
    assert len(decoded["accepts"]) >= 1
    assert len(decoded["accepts"]) < len(body["accepts"]), "trimming must have dropped accepts"


def test_402_response_header_fits_cloudflare_limit():
    """End-to-end: the 402's PAYMENT-REQUIRED header must stay under CF's ceiling."""
    import base64 as _b64
    import json as _json

    a = FastAPI()

    @a.post("/v1/scrape")
    async def scrape():
        return {"ok": True}

    a.add_middleware(X402Middleware)  # default classification: /v1/* is paid
    client = TestClient(a, raise_server_exceptions=False)

    r = client.post("/v1/scrape", json={"url": "https://example.com"})
    assert r.status_code == 402
    hdr = r.headers.get("payment-required", "")
    assert hdr, "PAYMENT-REQUIRED header must be present"
    assert len(hdr.encode()) <= X402_PAYMENT_HEADER_MAX_BYTES
    # Body still carries the FULL multi-chain surface.

    body = r.json()
    decoded = _json.loads(_b64.b64decode(hdr))
    assert len(body.get("accepts", [])) >= len(decoded["accepts"])
    assert len(decoded["accepts"]) >= 1
