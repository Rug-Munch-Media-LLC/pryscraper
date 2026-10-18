"""Fail-closed settlement tests (P0): verified != settled.

Three money paths are covered:

1. ``X-Payment-Id`` middleware gate — a verified-but-unsettled payment gets
   a 402; the same payment is served once a success receipt exists.
2. ``/v1/x402/pay`` — a failed settle returns ``success: False`` and no
   usable ``payment_id`` / ``use_in_header``.
3. ``FacilitatorRouter.settle`` — the EIP-7702 fallback only mints a success
   receipt when the on-chain verify leg passed.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pry.api.api import app
from tests._x402_stage_fakes import (
    _fake_middleware,
    _FakeApp,
    _FakeHandler,
    _Recorder,
)

PAID_PATH = "/v1/scrape"
CALLER = "10.0.0.9"
client = TestClient(app)


class _SettlingHandler(_FakeHandler):
    """Paid handler whose settled index + JSONL trail the gate reads."""

    def __init__(self, settlements_file) -> None:
        super().__init__(paid=True)
        self.settlements_file = settlements_file
        self._settled_txs = {}


async def _drive_headers(mw, payment_id: str) -> tuple[_Recorder, int | None]:
    recorder = _Recorder()
    scope = {
        "type": "http",
        "method": "POST",
        "path": PAID_PATH,
        "headers": [(b"x-payment-id", payment_id.encode())],
        "client": (CALLER, 1234),
    }
    await mw(scope, None, recorder)
    start = next((f for f in recorder.frames if f["type"] == "http.response.start"), None)
    return recorder, (start or {}).get("status")


class TestPreverifiedPaymentRequiresSettlement:
    async def test_unsettled_payment_is_402_then_200_after_settle(self, monkeypatch, tmp_path):
        trail = tmp_path / "settlements.jsonl"
        handler = _SettlingHandler(trail)
        mw = _fake_middleware(monkeypatch, app=_FakeApp(), handler=handler, network="base")

        _recorder, status = await _drive_headers(mw, "pay_unsettled")
        assert status == 402, "verified-but-unsettled payment must be refused"
        assert mw.app.calls == []
        assert mw.sent == [("scrape", PAID_PATH)]

        receipt = {"payment_id": "pay_unsettled", "success": True, "tx_hash": "0xabc"}
        trail.write_text(json.dumps(receipt) + "\n")

        _recorder, status = await _drive_headers(mw, "pay_unsettled")
        assert status == 200
        assert mw.app.calls, "settled payment must be served"


class TestPayRouteFailsClosed:
    def test_settle_failure_yields_no_payment_id(self):
        with (
            patch(
                "pry.payments.x402.X402Handler.verify_payment",
                AsyncMock(return_value={"verified": True, "reason": "", "settlement": None}),
            ),
            patch(
                "pry.payments.x402.X402Handler.settle_payment",
                AsyncMock(return_value={"success": False, "reason": "settle_reverted"}),
            ),
        ):
            response = client.post(
                "/v1/x402/pay",
                json={
                    "operation": "scrape",
                    "tx_hash": "0xdeadbeef",
                    "payer_wallet": "0xwallet",
                    "network": "base",
                    "asset": "USDC",
                    "amount_usd": 1.0,
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        data = body["data"]
        assert data["settled"] is False
        assert data["payment_id"] == ""
        assert data["use_in_header"] == {}


class TestFacilitatorEip7702FallbackFailsClosed:
    async def test_failed_verify_never_mints_success_receipt(self, monkeypatch):
        from pry.payments.x402.facilitator import FacilitatorRouter

        router = FacilitatorRouter(facilitators=[], self_hosted=False)
        verify = AsyncMock(return_value={"verified": False, "reason": "payTo mismatch"})
        monkeypatch.setattr(router, "_eip7702_verify", verify)

        receipt = await router.settle(
            payment_id="pay_eip",
            tx_hash="0xdead",
            network="base",
            asset="USDC",
            amount_usd=1.0,
        )
        assert receipt["success"] is False
        assert "payTo mismatch" in receipt["reason"]
        verify.assert_awaited_once()

    async def test_normalizer_never_upgrades_explicit_false(self):
        from pry.payments.x402.facilitator import FacilitatorRouter

        receipt = FacilitatorRouter(facilitators=[], self_hosted=False)._normalize_settlement(
            {"success": False, "error": "insufficient"},
            "pay_norm",
            "0xdead",
            "base",
            "external",
        )
        assert receipt["success"] is False
