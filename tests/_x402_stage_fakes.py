# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the split x402 enforcement stages.

Payment-critical: these cover the early-stage helpers extracted from
``X402Middleware.__call__`` (``enforcement_stages``) and the pure checks plus
verify→settle orchestration in ``enforcement_payment_checks`` /
``enforcement_payment``. No network, no facilitator, no Redis — collaborators
are injected fakes. The ordering assertions are the point: verify must be
consulted before settle, and settle must have happened before serving.
"""

from __future__ import annotations

import base64
import json
from typing import Any


def _sig(payload: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _scope(
    *,
    payment_sig: str = "",
    path: str = "/v1/scrape",
    caller: str | None = None,
    extra: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Build an ASGI scope carrying the x402 payment-signature header."""
    headers: list[tuple[bytes, bytes]] = [(b"payment-signature", payment_sig.encode())]
    for key, value in (extra or {}).items():
        headers.append((key.encode(), value))
    scope: dict[str, Any] = {"type": "http", "method": "POST", "path": path, "headers": headers}
    if caller is not None:
        scope["client"] = (caller, 12345)
    return scope


class _ReceiptLedger:
    """In-memory stand-in for the settlement receipt store.

    ``write`` is called once per settled request so tests can assert the
    settlement was recorded EXACTLY once (no double-record on replay).
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, settlement: dict[str, Any]) -> None:
        self.records.append(settlement)


def _decoded(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Reassemble an ASGI send stream into a status + headers + body dict."""
    start = next(f for f in frames if f["type"] == "http.response.start")
    body = b"".join(f.get("body", b"") for f in frames if f["type"] == "http.response.body")
    parsed_body: Any = None
    if body:
        try:
            parsed_body = json.loads(body)
        except ValueError:
            parsed_body = body
    return {
        "status": start["status"],
        "headers": dict(start.get("headers", [])),
        "body": parsed_body,
    }


class _Recorder:
    """Collects ASGI messages from a fake ``send`` callable."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.frames.append(message)


class _FakeApp:
    """Records that the wrapped app was served, with the scope it saw."""

    def __init__(self, status: int = 200) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status

    async def __call__(self, scope, receive, send):
        self.calls.append(scope)
        await send({"type": "http.response.start", "status": self.status, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


class _FakeHandler:
    """Fake X402Handler exposing the verify/settle contract the gate drives."""

    def __init__(
        self,
        *,
        verified: bool = True,
        settlement: dict[str, Any] | None = None,
        paid: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.verify_kwargs: dict[str, Any] = {}
        self.settle_kwargs: dict[str, Any] = {}
        self._verified = verified
        self._settlement = settlement if settlement is not None else {"success": True}
        self._paid = paid

    def refresh(self) -> None:
        self.calls.append("refresh")

    async def verify_payment(self, payment_id, tx_hash, **kwargs):
        self.calls.append("verify")
        self.verify_kwargs = {"payment_id": payment_id, "tx_hash": tx_hash, **kwargs}
        return {"verified": self._verified}

    async def settle_payment(self, payment_id, tx_hash, **kwargs):
        self.calls.append("settle")
        self.settle_kwargs = {"payment_id": payment_id, "tx_hash": tx_hash, **kwargs}
        return self._settlement

    def batch_settlement_status(self, batch_id: str) -> dict[str, Any]:
        """Per-item proof; default declines so batch tests opt in explicitly."""
        return getattr(self, "_batch_status", {"all_settled": False, "settled": []})

    def is_paid(self, payment_id, **kwargs):
        return self._paid


class _FakeMW:
    """Minimal middleware stand-in with only the attributes stages touch."""

    def __init__(self, *, handler=None, verifier=None, network="base") -> None:
        self.app = _FakeApp()
        self.handler = handler or _FakeHandler()
        self.network = network
        self._free = False
        self._verifier = verifier

    def _is_free(self, path):
        return self._free

    async def _send_payment_required(self, operation, path, send):
        assert self._verifier is not None
        await self._verifier(operation, path, send)


def _fake_middleware(monkeypatch, *, app=None, handler=None, network="base"):
    """Build a REAL ``X402Middleware`` with its only collaborators faked.

    Returns the middleware with a no-op limiter, a ``_send_payment_required``
    that records 402 challenges (via ``mw.sent``), and the supplied fake app +
    handler injected. ``monkeypatch`` is used so the substitutions unwind.
    """
    from pry.payments.x402_middleware.enforcement import X402Middleware

    mw = X402Middleware(app if app is not None else _FakeApp(), network=network)
    mw.handler = handler or _FakeHandler()
    mw._free = False
    mw.sent: list[tuple[str, str]] = []

    class _Allow:
        def check(self, _key):
            return True, {}

    mw.limiter = _Allow()
    monkeypatch.setattr(mw, "_is_free", lambda path: mw._free)

    async def _send_402(operation, path, send):
        mw.sent.append((operation, path))
        await send({"type": "http.response.start", "status": 402, "headers": []})
        await send({"type": "http.response.body", "body": b'{"error":"payment_required"}'})

    monkeypatch.setattr(mw, "_send_payment_required", _send_402)
    return mw
