"""Gate-level regression: the x402 payment gate only admits VALID credentials.

The gate is the revenue boundary. A prior implementation let ANY request whose
``Authorization`` header merely started with ``Bearer `` and was 8+ characters
bypass the payment challenge — ``Authorization: Bearer aaaaaaaa`` on a paid
route reached the resource for free. These tests pin the fail-closed contract
at the real ``X402Middleware`` boundary (stub ASGI app on a paid endpoint):

* an unrecognised Bearer token is 402-challenged and never reaches the app,
* a valid DB-issued ``pry_*`` key still passes (hosted customers not broken),
* a revoked / expired key is challenged, not served,
* the operator master key still passes,
* a credential-store failure denies (never grants).

Each test names the mutation it kills. Any test that would still pass after
reverting enforcement.py to the old ``Bearer `` prefix+length bypass is
decoration and must be deleted.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pry.payments.x402_middleware.enforcement import X402Middleware

PAID_PATH = "/v1/scrape"


class _StubApp:
    """Minimal ASGI app that records whether the paid resource was reached."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"RESOURCE"})


def _scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": PAID_PATH,
        "headers": headers,
        "query_string": b"",
    }


async def _call(middleware: X402Middleware, scope: dict) -> list[dict]:
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def _status(sent: list[dict]) -> int:
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"]


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated SQLite DB for api_keys_service (repo-standard db fixture)."""
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/gate.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_SessionLocal", None, raising=False)

    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/gate.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_owner_key(monkeypatch):
    """Pin the owner key OFF so the owner bypass cannot satisfy these tests."""
    monkeypatch.setenv("PRY_API_KEY", "")


# ── (a) Unrecognised Bearer token must NOT get the resource ────────────────


@pytest.mark.asyncio
async def test_bogus_bearer_token_is_challenged_not_served(db) -> None:
    """`Bearer aaaaaaaa` (the reported exploit) must be 402'd, not served.

    Kills: reverting the gate to the old `startswith(b"Bearer ") and
    len>7` bypass — that mutation makes app.called True / 200 for this token.
    """
    app = _StubApp()
    scope = _scope([(b"authorization", b"Bearer aaaaaaaa")])
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert not app.called, "an unvalidated bearer token must NOT reach the paid resource"
    assert _status(sent) == 402
    body = json.loads(
        b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
    )
    assert body, "challenge carries the payment-required body"


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [b"aaaaaaaa", b"not-a-real-key-at-all", b"BearerX", b"short"])
async def test_other_invalid_bearer_shapes_are_challenged(db, token: bytes) -> None:
    """Arbitrary token bytes never bypass the gate.

    Kills: any relaxed token-shape test reintroduced in credential.py that
    would accept these shapes as a credential.
    """
    app = _StubApp()
    sent = await _call(
        X402Middleware(app, wallet="0x0", network="base"),
        _scope([(b"authorization", b"Bearer " + token)]),
    )
    assert not app.called, f"invalid token {token!r} must not reach the paid resource"
    assert _status(sent) == 402


# ── (b) A valid key DOES get the resource ───────────────────────────────────


@pytest.mark.asyncio
async def test_valid_db_api_key_passes(db) -> None:
    """A live DB-issued pry_* key still bypasses the challenge.

    Kills: an over-tight fix that 402s valid hosted customers (deleting the
    bypass entirely without validating) — this test goes 402 without it.
    """
    from pry.core import api_keys_service

    issued = api_keys_service.issue_key(name="valid-customer")
    app = _StubApp()
    scope = _scope([(b"authorization", f"Bearer {issued['plaintext']}".encode())])
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert app.called, "a valid API key must reach the paid resource"
    assert _status(sent) == 200


@pytest.mark.asyncio
async def test_valid_master_key_passes(db, monkeypatch) -> None:
    """The operator master key still bypasses the challenge.

    Kills: a fix that only accepts DB keys and 402s the operator's own
    first-party / self-hosted credential.
    """
    from pry.core import settings as _settings_mod

    monkeypatch.setattr(_settings_mod.settings, "api_key", "operator-master-secret", raising=False)
    app = _StubApp()
    scope = _scope([(b"authorization", b"Bearer operator-master-secret")])
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert app.called, "the operator master key must reach the paid resource"
    assert _status(sent) == 200


# ── (c) Revoked / expired keys do NOT get the resource ─────────────────────


@pytest.mark.asyncio
async def test_revoked_key_is_challenged(db) -> None:
    """A revoked key is 402'd (fail closed), not served for free.

    Kills: a check that only matches the key's format/prefix without
    consulting the store, so a revoked key would still pass.
    """
    from pry.core import api_keys_service

    issued = api_keys_service.issue_key(name="to-revoke")
    assert api_keys_service.revoke_key(issued["key_id"]) is True
    app = _StubApp()
    scope = _scope([(b"authorization", f"Bearer {issued['plaintext']}".encode())])
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert not app.called, "a revoked key must NOT reach the paid resource"
    assert _status(sent) == 402


@pytest.mark.asyncio
async def test_expired_key_is_challenged(db) -> None:
    """An expired key is 402'd (fail closed).

    Kills: a store check that ignores expires_at.
    """
    from pry.core import api_keys_service

    issued = api_keys_service.issue_key(
        name="expired",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    app = _StubApp()
    scope = _scope([(b"authorization", f"Bearer {issued['plaintext']}".encode())])
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert not app.called, "an expired key must NOT reach the paid resource"
    assert _status(sent) == 402


# ── (3) Fail closed on validation error ────────────────────────────────────


@pytest.mark.asyncio
async def test_credential_store_outage_denies(db, monkeypatch) -> None:
    """If credential validation cannot be performed, DENY (never allow).

    Kills: a fail-OPEN variant that returns True when the store raises
    (e.g. swallowing the exception and defaulting to a pass).
    """
    from pry.core import api_keys_service

    issued = api_keys_service.issue_key(name="outage")
    plaintext = issued["plaintext"]

    def _boom(_token: str):
        raise RuntimeError("store offline")

    monkeypatch.setattr(api_keys_service, "authenticate", _boom)
    app = _StubApp()
    scope = _scope([(b"authorization", f"Bearer {plaintext}".encode())])
    sent = await _call(X402Middleware(app, wallet="0x0", network="base"), scope)
    assert not app.called, "a credential-store outage must NOT grant access"
    assert _status(sent) == 402
