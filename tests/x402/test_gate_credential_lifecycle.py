"""Gate-level regression: credential lifecycle and fail-closed admission (part 2).

Split from ``test_gate_bearer_credential.py``, which crossed the 200-line
structure cap. Same gate, same shared ASGI harness (``_gate_support``); this
half covers the states a live credential passes THROUGH rather than the shapes
it is refused in:

* a revoked / expired key is challenged, not served,
* a credential-store failure denies (never grants).

Each test names the mutation it kills.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from datetime import UTC, datetime, timedelta

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
