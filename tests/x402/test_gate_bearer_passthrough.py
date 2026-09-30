"""Gate-level regression: a VALID Bearer credential passes to inner auth (part 3).

Split out of ``tests/test_x402_final_hardening.py``, which crossed the 200-line
structure cap once the Bearer-gate suite was appended to it. The gate is the
revenue boundary, so the three things it must distinguish get their own files:

* ``test_gate_bearer_credential.py``      — invalid token SHAPES are challenged,
* ``test_gate_credential_lifecycle.py``   — revoked / expired / store outage deny,
* this file                               — a VALID key is NOT challenged.

The shared ASGI harness and the ``db`` / ``no_owner_key`` fixtures come from
``tests.x402._gate_support`` (not re-declared), so all three suites drive the
real ``X402Middleware`` through one definition.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from typing import Any

import pytest
from fastapi import FastAPI

from pry.payments.x402_middleware import X402Middleware
from tests.x402._gate_support import db as db, no_owner_key  # noqa: F401 — fixture params

pytestmark = pytest.mark.usefixtures("no_owner_key")


def _make_app() -> FastAPI:
    a = FastAPI()

    @a.get("/v1/scrape")
    async def scrape() -> dict[str, bool]:
        return {"ok": True}

    a.add_middleware(X402Middleware)
    return a


def test_x402_gate_passes_valid_bearer_credentials_to_inner_auth(db) -> None:
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
