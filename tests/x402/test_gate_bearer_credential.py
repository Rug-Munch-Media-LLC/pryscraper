"""Gate-level regression: the x402 payment gate only admits VALID credentials (part 1).

The gate is the revenue boundary. A prior implementation let ANY request whose
``Authorization`` header merely started with ``Bearer `` and was 8+ characters
bypass the payment challenge — ``Authorization: Bearer aaaaaaaa`` on a paid
route reached the resource for free. These tests pin the fail-closed contract
at the real ``X402Middleware`` boundary (stub ASGI app on a paid endpoint).

The shared ASGI harness (``_StubApp`` / ``_scope`` / ``_call`` / ``db``) lives in
``_gate_support``; the revoked/expired and fail-closed cases are in
``test_gate_credential_lifecycle.py``.

* an unrecognised Bearer token is 402-challenged and never reaches the app,
* a valid DB-issued ``pry_*`` key still passes (hosted customers not broken),
* the operator master key still passes.

Each test names the mutation it kills. Any test that would still pass after
reverting enforcement.py to the old ``Bearer `` prefix+length bypass is
decoration and must be deleted.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

import json

import pytest

from pry.payments.x402_middleware.enforcement import X402Middleware
from tests.x402._gate_support import (
    _call,
    _scope,
    _status,
    _StubApp,
    db as db,  # fixture re-exported for the test params
    no_owner_key,
)

pytestmark = pytest.mark.usefixtures(no_owner_key.__name__)


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
