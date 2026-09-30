"""Shared helpers and fixtures for the x402 gate tests (split out of the gate files).

``test_gate_bearer_credential.py`` and ``test_internal_gate_middleware.py`` each
carried their own ``_StubApp`` / ``_scope`` / ``_call`` definitions and both
crossed the 200-line structure cap. The one shared ASGI harness lives here so
the two suites exercise the real middleware through one definition instead of
two lookalikes, and so the ``db`` fixture has a single owner.

The Bearer-credential and internal-gate suites use DIFFERENT scope shapes on
purpose: the credential file omits ``client`` entirely (it only exercises
``Authorization``), while the internal file must carry a socket peer because the
first-party HMAC is bound to the caller address. ``_caller`` is therefore opt-in.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

import time
from typing import Any

import pytest

from pry.payments.x402_middleware.enforcement import X402Middleware
from pry.payments.x402_middleware.internal import (
    INTERNAL_SIG_HEADER,
    INTERNAL_TIMESTAMP_HEADER,
    INTERNAL_TOKEN_HEADER,
    internal_signature,
)

PAID_PATH = "/v1/scrape"
CALLER = "10.0.0.7"
INTERNAL_TOKEN = "internal-secret"


class _StubApp:
    """Minimal ASGI app that records whether the paid resource was reached.

    The credential suite asserts on the response body it emits (``RESOURCE``);
    the internal suite only asserts that it was reached. One app, both uses.
    """

    def __init__(self) -> None:
        """Track invocation for assertions."""
        self.called = False

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        """ASGI entry point: mark reached and return a 200."""
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"RESOURCE"})


def _scope(
    headers: list[tuple[bytes, bytes]], path: str = PAID_PATH, caller: str | None = None
) -> dict:
    """Build an ASGI scope. ``caller`` is omitted unless the suite binds to a peer."""
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
        "query_string": b"",
    }
    if caller is not None:
        scope["client"] = (caller, 51000)
    return scope


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


def _internal_headers(
    method: str = "POST",
    path: str = PAID_PATH,
    timestamp: str | None = None,
    token: str = INTERNAL_TOKEN,
) -> list[tuple[bytes, bytes]]:
    """Mint a well-formed first-party credential header set."""
    stamp = timestamp if timestamp is not None else str(int(time.time()))
    sig = internal_signature(token, method, path, CALLER, stamp)
    return [
        (INTERNAL_TOKEN_HEADER, token.encode()),
        (INTERNAL_SIG_HEADER, sig.encode()),
        (INTERNAL_TIMESTAMP_HEADER, stamp.encode()),
    ]


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


@pytest.fixture
def no_owner_key(monkeypatch) -> None:
    """Pin the owner key OFF so the owner bypass cannot satisfy the credential tests.

    The original gate file held this as an ``autouse`` fixture. It is explicit
    here because the internal-gate suite sets ``PRY_API_KEY`` itself in two
    tests (``test_owner_key_still_passes`` and the external-bearer case), and
    the internal suite must not inherit the pin.
    """
    monkeypatch.setenv("PRY_API_KEY", "")
