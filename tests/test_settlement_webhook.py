# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the x402 settlement webhook (audit item #8).

Covers: env-unset no-op, POST fired with the receipt payload, webhook
failure never affecting the settlement result, and idempotency (a cached
settle does not re-fire).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest
import respx
from httpx import Response

from pry.payments.x402.handler import X402Handler, fire_settlement_webhook

WEBHOOK_URL = "https://hooks.example.com/settlements"


@pytest.fixture
def handler(tmp_path: Path) -> X402Handler:
    """Return a handler with temp audit files and a mocked facilitator."""
    with (
        patch("pry.payments.x402.handler.FacilitatorRouter"),
        patch("pry.payments.x402.handler.get_facilitator_router") as mock_get,
    ):
        mock_instance = MagicMock()
        mock_instance.settle = AsyncMock(
            return_value={"success": True, "tx_hash": "0xabc", "network": "base"}
        )
        mock_get.return_value = mock_instance
        yield X402Handler(
            payments_file=tmp_path / "payments.jsonl",
            settlements_file=tmp_path / "settlements.jsonl",
        )


@pytest.fixture
def webhook_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Enable the settlement webhook with a signing secret + temp log dir."""
    monkeypatch.setenv("PRY_SETTLEMENT_WEBHOOK_URL", WEBHOOK_URL)
    monkeypatch.setenv("PRY_WEBHOOK_SECRET", "test-secret")
    import pry.api.webhook_delivery as wd

    monkeypatch.setattr(wd, "WEBHOOK_DIR", tmp_path / "webhooks")
    monkeypatch.setattr(wd.settings, "webhook_secret", "test-secret")
    # hooks.example.com is an RFC-2606 reserved name (NXDOMAIN) — respx
    # intercepts httpx but not socket.getaddrinfo, so the SSRF validator
    # would reject it as unresolvable. Bypass validation: these tests
    # exercise delivery/signing logic, not the SSRF guard (covered in
    # tests/test_webhook_delivery.py).
    monkeypatch.setattr(wd, "_validate_url", lambda url: (url, None))


# ---------------------------------------------------------------------------
# fire_settlement_webhook helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_webhook_disabled_when_env_unset(monkeypatch: pytest.MonkeyPatch):
    """Empty/unset env → no HTTP call, no error."""
    monkeypatch.delenv("PRY_SETTLEMENT_WEBHOOK_URL", raising=False)
    with respx.mock:
        route = respx.post(WEBHOOK_URL).mock(return_value=Response(200))
        await fire_settlement_webhook({"success": True})
        assert route.call_count == 0


@pytest.mark.asyncio
async def test_fire_webhook_posts_receipt_payload(webhook_env):
    """Env set → POST fired with the settlement receipt payload."""
    receipt = {"success": True, "tx_hash": "0xabc", "payment_id": "p1"}
    with respx.mock:
        route = respx.post(WEBHOOK_URL).mock(return_value=Response(200))
        await fire_settlement_webhook(receipt)
        assert route.call_count == 1
        sent = route.calls.last.request
        assert sent.headers["X-Pry-Event"] == "x402.settlement"
        assert sent.headers["X-Pry-Signature"].startswith("sha256=")
        import json

        body = json.loads(sent.content)
        assert body["tx_hash"] == "0xabc"
        assert body["payment_id"] == "p1"


# ---------------------------------------------------------------------------
# settle_payment integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settle_no_webhook_when_env_unset(handler: X402Handler, monkeypatch):
    """Env unset → settle succeeds, no HTTP call, no error."""
    monkeypatch.delenv("PRY_SETTLEMENT_WEBHOOK_URL", raising=False)
    with respx.mock:
        route = respx.post(WEBHOOK_URL).mock(return_value=Response(200))
        result = await handler.settle_payment("p1", "0xabc", network="base")
        assert result["success"] is True
        assert route.call_count == 0


@pytest.mark.asyncio
async def test_settle_fires_webhook_on_new_settlement(handler: X402Handler, webhook_env):
    """Env set → new settlement fires the webhook with the receipt."""
    with respx.mock:
        route = respx.post(WEBHOOK_URL).mock(return_value=Response(200))
        result = await handler.settle_payment("p1", "0xabc", network="base")
        assert result["success"] is True
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_settle_succeeds_even_when_webhook_fails(handler: X402Handler, webhook_env):
    """Webhook failure (HTTP 400) must NOT affect the settlement result."""
    with respx.mock:
        respx.post(WEBHOOK_URL).mock(return_value=Response(400))
        result = await handler.settle_payment("p1", "0xabc", network="base")
        assert result["success"] is True


@pytest.mark.asyncio
async def test_settle_succeeds_even_when_webhook_raises(handler: X402Handler, webhook_env):
    """A raising delivery path must not propagate into the payment flow."""
    with patch(
        "pry.payments.x402.handler.fire_settlement_webhook",
        side_effect=RuntimeError("boom"),
    ):
        result = await handler.settle_payment("p1", "0xabc", network="base")
        assert result["success"] is True


@pytest.mark.asyncio
async def test_settle_idempotent_does_not_refire_webhook(handler: X402Handler, webhook_env):
    """Second settle of the same tx hits the cache → no second webhook."""
    with respx.mock:
        route = respx.post(WEBHOOK_URL).mock(return_value=Response(200))
        first = await handler.settle_payment("p1", "0xabc", network="base")
        second = await handler.settle_payment("p1", "0xabc", network="base")
        assert first["success"] is True
        assert second["success"] is True
        assert route.call_count == 1
