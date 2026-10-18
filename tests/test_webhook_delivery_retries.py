# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for webhook_delivery.py — deliver() retry and header behaviour."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

from typing import TYPE_CHECKING
from unittest.mock import patch

import httpx
import pytest
import respx

from pry.api.webhook_delivery import WebhookDelivery

if TYPE_CHECKING:
    from pathlib import Path

import httpx
import pytest
import respx

from pry.api.webhook_delivery import WebhookDelivery


@pytest.fixture
def wh(tmp_path: Path) -> WebhookDelivery:
    """Return a webhook delivery with temp paths so tests don't collide."""
    with (
        patch("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "webhooks"),
        # deliver() reads the retry backoff from this module constant; keep
        # retry behaviour, not the wall-clock sleep.
        patch("pry.api.webhook_delivery._RETRY_DELAY", 0.001),
        patch("pry.api.webhook_support.settings.webhook_secret", "test-secret"),
        patch(
            "pry.api.webhook_delivery._validate_url",
            side_effect=lambda url: (url, None),
        ),
    ):
        w = WebhookDelivery(signing_secret="test-key")
        yield w


# ---------------------------------------------------------------------------
# deliver — success
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_deliver_success(wh: WebhookDelivery):
    respx.post("https://hook.example.com").mock(return_value=httpx.Response(200, json={"ok": True}))
    result = await wh.deliver("https://hook.example.com", {"event": "test"})
    assert result["success"] is True
    assert result["status"] == 200


@respx.mock
@pytest.mark.asyncio
async def test_deliver_retries_on_500(wh: WebhookDelivery):
    """Server errors (500+) should be retried."""
    route = respx.post("https://hook.example.com")
    route.mock(return_value=httpx.Response(500, json={"error": "internal"}))
    result = await wh.deliver("https://hook.example.com", {"event": "test"}, max_retries=2)
    assert result["success"] is False
    assert result["error"] == "Max retries exceeded"


@respx.mock
@pytest.mark.asyncio
async def test_deliver_client_error_no_retry(wh: WebhookDelivery):
    """4xx errors should not be retried — sent to dead letter immediately."""
    route = respx.post("https://hook.example.com")
    route.mock(return_value=httpx.Response(400, json={"error": "bad request"}))
    result = await wh.deliver("https://hook.example.com", {"event": "test"}, max_retries=3)
    assert result["success"] is False
    assert "Client error" in result.get("error", "")

    # Should be in dead letter
    items = wh.get_dead_letter()
    assert len(items) == 1
    assert "HTTP 400" in items[0]["reason"]


@respx.mock
@pytest.mark.asyncio
async def test_deliver_network_error_retries(wh: WebhookDelivery):
    """Network errors should be retried."""
    route = respx.post("https://hook.example.com")
    route.mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    result = await wh.deliver("https://hook.example.com", {"event": "test"}, max_retries=2)
    assert result["success"] is True
    assert result["attempts"] == 2


@respx.mock
@pytest.mark.asyncio
async def test_deliver_all_retries_fail(wh: WebhookDelivery):
    """All retries exhausted should go to dead letter."""
    route = respx.post("https://hook.example.com")
    route.mock(side_effect=httpx.ConnectError("always down"))
    result = await wh.deliver("https://hook.example.com", {"event": "test"}, max_retries=2)
    assert result["success"] is False
    assert result["error"] == "Max retries exceeded"

    items = wh.get_dead_letter()
    assert len(items) == 1
    assert "Max retries" in items[0]["reason"]


# ---------------------------------------------------------------------------
# deliver — signing headers
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_deliver_includes_signing_headers(wh: WebhookDelivery):
    route = respx.post("https://hook.example.com")
    route.mock(return_value=httpx.Response(200, json={"ok": True}))

    await wh.deliver("https://hook.example.com", {"event": "test"})

    sent = route.calls[0].request
    assert "X-Pry-Signature" in sent.headers
    assert sent.headers["X-Pry-Signature"].startswith("sha256=")
    assert "X-Pry-Event" in sent.headers
    assert sent.headers["X-Pry-Event"] == "monitor.change"
    assert "X-Pry-Timestamp" in sent.headers


# ---------------------------------------------------------------------------
# deliver — custom event type
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_deliver_custom_event_type(wh: WebhookDelivery):
    route = respx.post("https://hook.example.com")
    route.mock(return_value=httpx.Response(200, json={"ok": True}))

    await wh.deliver("https://hook.example.com", {"event": "test"}, event_type="custom.event")
    assert route.calls[0].request.headers["X-Pry-Event"] == "custom.event"
