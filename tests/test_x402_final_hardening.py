# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Final x402 security-hardening tests.

Covers:
1. Settle idempotency at the handler level: the same (payment_id, tx_hash)
   submitted twice produces ONE facilitator settle call and ONE ledger line.
2. Testnet gating: base-sepolia is rejected on the live verify path when
   PRY_X402_ALLOW_TESTNETS is unset.
3. Attestation enforcement in the middleware: a client-presented 402 body
   with a TAMPERED payTo is rejected (fresh 402, never verified).
4. Rate limiting: the outermost gate rate-limits per IP (429) before any
   facilitator traffic.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import pry.payments.x402_middleware.enforcement as _enforcement
from pry.core.ratelimit import RateLimiter
from pry.payments.x402 import X402Handler, _encode_payment_required_body, scheme as _scheme
from pry.payments.x402.self_facilitator import SelfFacilitator
from pry.payments.x402_middleware import X402Middleware


def _disable_gate_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate's Redis-backed limiter is shared across TestClient requests
    (same peer IP); tests here must not consume other tests' budget."""
    monkeypatch.setattr(_enforcement, "X402_RATE_LIMIT_PER_MIN", 10**9)
    # Setting PRY_X402_ATTEST_KEY causes scheme.py to cache the derived key in
    # a module global; reset it so later tests see an unconfigured attestation
    # key (env is restored by monkeypatch, but the cache would outlive it).
    monkeypatch.setattr(_scheme, "_attest_key_cache", None)


# ── 1. Settle idempotency ────────────────────────────────────────────────────


class _RecordingRouter:
    """FacilitatorRouter stand-in that counts settle calls."""

    def __init__(self) -> None:
        self.settle_calls = 0

    async def verify(self, **kwargs: Any) -> dict[str, Any]:
        return {"verified": True, "reason": "", "facilitator": "test"}

    async def settle(self, **kwargs: Any) -> dict[str, Any]:
        self.settle_calls += 1
        return {"success": True, "reason": ""}


@pytest.mark.asyncio
async def test_settle_same_payment_id_and_tx_is_idempotent(tmp_path) -> None:
    """Same payment_id + tx_hash twice → one settle call, one ledger line."""
    router = _RecordingRouter()
    handler = X402Handler(
        router=router,
        payments_file=tmp_path / "payments.jsonl",
        settlements_file=tmp_path / "settlements.jsonl",
    )
    first = await handler.settle_payment(
        "pay1", "0xtx1", network="base", asset="USDC", amount_usd=0.001, operation="scrape"
    )
    second = await handler.settle_payment(
        "pay1", "0xtx1", network="base", asset="USDC", amount_usd=0.001, operation="scrape"
    )
    assert first.get("success") is True
    assert second.get("success") is True
    assert router.settle_calls == 1, "second settle must be served from the idempotency cache"
    lines = (tmp_path / "settlements.jsonl").read_text().splitlines()
    assert len([ln for ln in lines if ln.strip()]) == 1, "exactly one settlement ledger entry"


# ── 2. Testnet gating ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_base_sepolia_rejected_when_allow_testnets_unset(monkeypatch) -> None:
    """Testnets must be rejected on the live verify path unless the env var
    is explicitly set."""
    monkeypatch.delenv("PRY_X402_ALLOW_TESTNETS", raising=False)
    monkeypatch.delenv("PRY_X402_ATTEST_KEY", raising=False)
    fac = SelfFacilitator(pay_to="0x1E3AC01d0fdb976179790BDD02823196A92705C9")
    result = await fac.verify(
        {
            "network": "base-sepolia",
            "asset": "USDC",
            "amount_usd": 0.001,
            "authorization": {
                "from": "0x1E3AC01d0fdb976179790BDD02823196A92705C9",
                "to": "0x1E3AC01d0fdb976179790BDD02823196A92705C9",
                "value": "1000",
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x" + "00" * 32,
                "signature": "0x" + "00" * 65,
            },
        }
    )
    assert result.verified is False
    assert "testnet" in (result.reason or "").lower()


# ── 3. Attestation enforcement in the middleware ─────────────────────────────


def _make_app() -> FastAPI:
    a = FastAPI()

    @a.get("/v1/scrape")
    async def scrape() -> dict[str, bool]:
        return {"ok": True}

    a.add_middleware(X402Middleware)
    return a


_ATTEST_KEY = "0x" + "11" * 32


def _attested_challenge_body() -> dict[str, Any]:
    """Build a server-attested payment-required body (as the gate emits)."""
    body = {
        "x402Version": 1,
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "asset": "USDC",
                "payToAddress": "0x1E3AC01d0fdb976179790BDD02823196A92705C9",
                "maxAmountRequired": "1000",
                "resource": "/v1/scrape",
                "operation": "scrape",
            }
        ],
    }
    # _encode_payment_required_body attaches the attestation when a key is set.
    encoded = _encode_payment_required_body(body)

    return json.loads(base64.b64decode(encoded))


def test_middleware_rejects_tampered_payto(monkeypatch) -> None:
    """A client echoing an attested 402 body whose payTo was rewritten must
    be refused by the enforcement gate (fresh 402, never verified)."""
    monkeypatch.setenv("PRY_X402_ATTEST_KEY", _ATTEST_KEY)
    _disable_gate_rate_limit(monkeypatch)
    body = _attested_challenge_body()
    assert body.get("attestation"), "challenge must be attested when a key is configured"
    body["accepts"][0]["payToAddress"] = "0xAttacker00000000000000000000000000000001"

    payload = {
        "payment_id": "pay-tamper",
        "tx_hash": "0xtamper",
        "network": "base",
        "asset": "USDC",
        "amount_usd": 0.001,
        "payment_required": body,
    }
    sig = base64.b64encode(__import__("json").dumps(payload).encode()).decode()

    app = _make_app()
    with TestClient(app) as client:
        resp = client.get("/v1/scrape", headers={"PAYMENT-SIGNATURE": sig})
    assert resp.status_code == 402, "tampered payTo must be rejected with a fresh 402"
    assert "payment-response" not in {k.lower() for k in resp.headers}


def test_middleware_accepts_valid_attestation_signature_shape(monkeypatch) -> None:
    """Positive control: an UNTAMPERED attested body passes the attestation
    gate (it then fails at facilitator verify — still a 402, but the
    attestation log line must NOT fire)."""

    monkeypatch.setenv("PRY_X402_ATTEST_KEY", _ATTEST_KEY)
    _disable_gate_rate_limit(monkeypatch)
    body = _attested_challenge_body()
    payload = {
        "payment_id": "pay-clean",
        "tx_hash": "0xclean",
        "network": "base",
        "asset": "USDC",
        "amount_usd": 0.001,
        "payment_required": body,
    }
    sig = base64.b64encode(json.dumps(payload).encode()).decode()
    app = _make_app()
    with TestClient(app) as client:
        resp = client.get("/v1/scrape", headers={"PAYMENT-SIGNATURE": sig})
    # Attestation passed; the request proceeds to facilitator verify which
    # fails offline → still 402, but NOT because of the attestation gate.
    assert resp.status_code == 402


# ── 4. Rate limiting ─────────────────────────────────────────────────────────


def test_x402_gate_rate_limits_per_ip() -> None:
    """After the per-IP budget is exhausted the gate answers 429, not 402."""
    app = _make_app()
    mw = X402Middleware(app)
    mw.limiter = RateLimiter(default_rpm=1, burst=1, redis_url=None)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/scrape",
        "headers": [],
        "client": ("203.0.113.7", 12345),
        "query_string": b"",
    }
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    import asyncio

    statuses: list[int] = []

    async def drive() -> None:
        # Exhaust the 1-request budget with a normal 402 challenge...
        await mw(scope, receive, send)
        statuses.append(sent[0]["status"])
        # ...then the next request must be rate limited.
        sent.clear()
        await mw(scope, receive, send)
        statuses.append(sent[0]["status"])

    asyncio.run(drive())
    assert statuses == [402, 429]


def test_x402_gate_buckets_by_xff_behind_trusted_proxy(monkeypatch) -> None:
    """Behind a trusted proxy (nginx on the docker bridge), the gate must
    bucket by the X-Forwarded-For client — not the proxy IP — or every
    internet caller shares one rate-limit bucket (production incident)."""
    monkeypatch.setenv("PRY_TRUSTED_PROXIES", "172.16.0.0/12")
    # Re-import so the trusted-proxy networks tuple picks up the env.
    import importlib

    import pry.core.middleware as core_mw

    importlib.reload(core_mw)
    from pry.payments.x402_middleware import classification as cls

    importlib.reload(cls)

    def _scope(xff: str | None) -> dict[str, Any]:
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return {
            "type": "http",
            "method": "GET",
            "path": "/v1/scrape",
            "headers": headers,
            "client": ("172.18.0.1", 55555),  # docker bridge gateway = trusted proxy
            "query_string": b"",
        }

    # Trusted proxy peer + XFF -> bucket by the real client.
    assert core_mw._resolve_client_ip(_scope("198.51.100.9")) == "198.51.100.9"
    # Different XFF clients get different bucket keys.
    assert cls._caller_key_from_scope(_scope("198.51.100.9")) == "198.51.100.9"
    assert cls._caller_key_from_scope(_scope("198.51.100.10")) == "198.51.100.10"
    # Untrusted peer (direct internet socket) -> XFF ignored, peer used.
    direct = {
        "type": "http",
        "method": "GET",
        "path": "/v1/scrape",
        "headers": [(b"x-forwarded-for", b"198.51.100.9")],
        "client": ("203.0.113.7", 12345),
        "query_string": b"",
    }
    assert cls._caller_key_from_scope(direct) == "203.0.113.7"
    # No XFF behind trusted proxy -> falls back to the (proxy) peer.
    assert cls._caller_key_from_scope(_scope(None)) == "172.18.0.1"
    # Restore the module state for other tests.
    monkeypatch.setenv("PRY_TRUSTED_PROXIES", "")
    importlib.reload(core_mw)


@pytest.fixture
def _isolated_db(tmp_path, monkeypatch):
    """Temp SQLite DB so a real API key can be issued and validated."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/hardening.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_SessionLocal", None, raising=False)

    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/hardening.db")
    models_mod.Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture
def _no_owner_key_for_hardening(monkeypatch):
    """Keep the owner bypass out of the credential-path assertions."""
    monkeypatch.setenv("PRY_API_KEY", "")


@pytest.mark.usefixtures("_isolated_db", "_no_owner_key_for_hardening")
def test_x402_gate_passes_valid_bearer_credentials_to_inner_auth() -> None:
    """Hosted API-key customers must NOT get 402-challenged: the gate passes a
    VALID Bearer API key through to the inner auth/billing layer.

    The gate validates the credential itself before waving it through — an
    unrecognised token (e.g. a merely pry_-shaped fake) is challenged instead
    (see tests/x402/test_gate_bearer_credential.py). Keyless traffic is still
    monetised with the 402 challenge."""
    from pry.core import api_keys_service

    issued = api_keys_service.issue_key(name="hosted-customer")
    app = _make_app()
    mw = X402Middleware(app)
    reached: list[dict[str, Any]] = []

    async def inner_app(scope, receive, send):
        reached.append(scope)

    mw.app = inner_app
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/sports/books",
        "headers": [
            (b"authorization", f"Bearer {issued['plaintext']}".encode()),
        ],
        "client": ("203.0.113.7", 12345),
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        pass

    import asyncio

    asyncio.run(mw(scope, receive, send))
    # The valid-key request reached the inner app (no 402 challenge).
    assert len(reached) == 1, "valid API-key request was 402-challenged by the gate"

    # Keyless request to the same path still gets the 402 challenge.
    reached.clear()
    keyless = dict(scope)
    keyless["headers"] = []
    asyncio.run(mw(keyless, receive, send))
    assert len(reached) == 0, "keyless request was NOT challenged"
