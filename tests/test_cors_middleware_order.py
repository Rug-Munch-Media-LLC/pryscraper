"""CORS middleware ordering: direct-send 401/402/429 must carry ACAO.

``X402Middleware`` (402) and ``PryHttpMiddleware`` (401/429) call ``send()``
directly, bypassing the router. CORS is therefore only effective when it is
the OUTERMOST middleware (added last). These tests reproduce the old ordering
and pin the fixed one.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

ORIGIN = "https://pryscraper.com"
ALLOWED = [
    "https://pryscraper.com",
    "https://api.pryscraper.com",
    "http://localhost:3000",
]


class _RejectMiddleware:
    """A direct-send middleware, like the auth/x402 gates."""

    def __init__(self, app, status: int = 401):
        self.app = app
        self.status = status

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"detail":"nope"}'})


def _cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware, allow_origins=ALLOWED, allow_methods=["*"], allow_headers=["*"]
    )


def _wrong_order_app(status: int = 401) -> FastAPI:
    """Old wiring: CORS added FIRST => innermost, reject gate outermost."""
    app = FastAPI()
    _cors(app)
    app.add_middleware(_RejectMiddleware, status=status)
    return app


def _right_order_app(status: int = 401) -> FastAPI:
    """Fixed wiring: CORS added LAST => outermost, wraps direct sends."""
    app = FastAPI()
    app.add_middleware(_RejectMiddleware, status=status)
    _cors(app)
    return app


def test_wrong_order_reproduces_missing_acao():
    resp = TestClient(_wrong_order_app(401)).get("/anything", headers={"Origin": ORIGIN})
    assert resp.status_code == 401
    assert "access-control-allow-origin" not in resp.headers


def test_wrong_order_reproduces_missing_acao_on_402():
    resp = TestClient(_wrong_order_app(402)).get("/paid", headers={"Origin": ORIGIN})
    assert resp.status_code == 402
    assert "access-control-allow-origin" not in resp.headers


def test_right_order_exposes_acao_on_401():
    resp = TestClient(_right_order_app(401)).get("/anything", headers={"Origin": ORIGIN})
    assert resp.status_code == 401
    assert resp.headers["access-control-allow-origin"] == ORIGIN


def test_right_order_exposes_acao_on_402():
    resp = TestClient(_right_order_app(402)).get("/paid", headers={"Origin": ORIGIN})
    assert resp.status_code == 402
    assert resp.headers["access-control-allow-origin"] == ORIGIN


def test_preflight_still_returns_200_and_methods():
    client = TestClient(_right_order_app(401))
    resp = client.options(
        "/anything",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == ORIGIN
    assert "POST" in resp.headers["access-control-allow-methods"]


def test_real_app_402_carries_acao():
    """The assembled app: a keyless paid request reaches the 402 challenge
    with CORS headers, so a browser can read it."""
    from pry.api.api import app

    client = TestClient(app)
    resp = client.post(
        "/v1/scrape", json={"url": "https://example.com"}, headers={"Origin": ORIGIN}
    )
    assert resp.status_code == 402, resp.text[:200]
    assert resp.headers.get("access-control-allow-origin") == ORIGIN


def test_real_app_401_carries_acao():
    """A keyless, non-loopback peer is rejected by the auth middleware with a
    direct send; CORS must still expose the rejection to the browser."""
    from pry.api.api import app

    client = TestClient(app, client=("203.0.113.9", 12345))
    resp = client.post(
        "/v1/browser/render", json={"url": "https://example.com"}, headers={"Origin": ORIGIN}
    )
    assert resp.status_code == 401, resp.text[:200]
    assert resp.headers.get("access-control-allow-origin") == ORIGIN
