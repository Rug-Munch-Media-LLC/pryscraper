# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for webhook_delivery.py — HMAC-signed webhook delivery with retries."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

import httpx
import pytest
import respx

from pry.api.webhook_delivery import WebhookDelivery, WebhookSecretNotConfigured


@pytest.fixture
def wh(tmp_path: Path) -> WebhookDelivery:
    """Return a webhook delivery with temp paths so tests don't collide."""
    with (
        patch("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "webhooks"),
        patch("pry.api.webhook_delivery.settings.webhook_secret", "test-secret"),
    ):
        w = WebhookDelivery(signing_secret="test-key")
        yield w


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def test_init_creates_dirs(wh: WebhookDelivery, tmp_path: Path):
    assert (tmp_path / "webhooks").exists()


def test_init_signing_secret_resolution(monkeypatch):
    """Should use explicit secret over env over settings."""
    w = WebhookDelivery(signing_secret="explicit")
    assert w.signing_secret == "explicit"


def test_init_falls_to_settings(monkeypatch):
    monkeypatch.delenv("PRY_WEBHOOK_SECRET", raising=False)
    with patch("pry.api.webhook_delivery.settings.webhook_secret", "from-settings"):
        w = WebhookDelivery()
        assert w.signing_secret == "from-settings"


# ---------------------------------------------------------------------------
# sign_payload
# ---------------------------------------------------------------------------


def test_sign_payload_consistent(wh: WebhookDelivery):
    sig1 = wh.sign_payload({"a": 1, "b": 2})
    sig2 = wh.sign_payload({"b": 2, "a": 1})  # same dict, different order
    assert sig1 == sig2  # deterministic


def test_sign_payload_different_key_yields_different_sig(wh: WebhookDelivery):
    sig1 = wh.sign_payload({"a": 1})
    wh.signing_secret = "different-key"
    sig2 = wh.sign_payload({"a": 1})
    assert sig1 != sig2


# ---------------------------------------------------------------------------
# _log / _load_log
# ---------------------------------------------------------------------------


def test_log_append_and_load(wh: WebhookDelivery, tmp_path: Path):
    wh._log({"url": "http://example.com", "status": 200})
    assert len(wh.log) == 1
    # reload from disk
    dl_path = wh.delivery_log
    dl_dir = dl_path.parent
    w2 = WebhookDelivery(signing_secret="test-key")
    w2.delivery_log = dl_path
    w2.dead_letter = dl_dir / "dead_letter.jsonl"
    w2._load_log()
    assert len(w2.log) == 1
    assert w2.log[0]["status"] == 200


# ---------------------------------------------------------------------------
# _dead_letter / get_dead_letter
# ---------------------------------------------------------------------------


def test_dead_letter_store_and_retrieve(wh: WebhookDelivery):
    wh._dead_letter({"key": "val"}, "http://x.com", "test reason")
    items = wh.get_dead_letter()
    assert len(items) == 1
    assert items[0]["reason"] == "test reason"
    assert items[0]["url"] == "http://x.com"


def test_dead_letter_empty(wh: WebhookDelivery):
    assert wh.get_dead_letter() == []


def test_dead_letter_multiple(wh: WebhookDelivery):
    wh._dead_letter({"a": 1}, "http://a.com", "reason a")
    wh._dead_letter({"b": 2}, "http://b.com", "reason b")
    items = wh.get_dead_letter()
    assert len(items) == 2


# ---------------------------------------------------------------------------
# retry_dead_letter
# ---------------------------------------------------------------------------


def test_retry_dead_letter_returns_items(wh: WebhookDelivery):
    wh._dead_letter({"x": 1}, "http://x.com", "err")
    result = wh.retry_dead_letter()
    assert result["total"] == 1
    assert len(result["items"]) == 1


# ---------------------------------------------------------------------------
# deliver — success
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_deliver_success(wh: WebhookDelivery):
    respx.post("http://hook.example.com").mock(return_value=httpx.Response(200, json={"ok": True}))
    result = await wh.deliver("http://hook.example.com", {"event": "test"})
    assert result["success"] is True
    assert result["status"] == 200


@respx.mock
@pytest.mark.asyncio
async def test_deliver_retries_on_500(wh: WebhookDelivery):
    """Server errors (500+) should be retried."""
    route = respx.post("http://hook.example.com")
    route.mock(return_value=httpx.Response(500, json={"error": "internal"}))
    result = await wh.deliver(
        "http://hook.example.com", {"event": "test"}, max_retries=2, retry_delay=0.01
    )
    assert result["success"] is False
    assert result["error"] == "Max retries exceeded"


@respx.mock
@pytest.mark.asyncio
async def test_deliver_client_error_no_retry(wh: WebhookDelivery):
    """4xx errors should not be retried — sent to dead letter immediately."""
    route = respx.post("http://hook.example.com")
    route.mock(return_value=httpx.Response(400, json={"error": "bad request"}))
    result = await wh.deliver(
        "http://hook.example.com", {"event": "test"}, max_retries=3, retry_delay=0.01
    )
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
    route = respx.post("http://hook.example.com")
    route.mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    result = await wh.deliver(
        "http://hook.example.com", {"event": "test"}, max_retries=2, retry_delay=0.01
    )
    assert result["success"] is True
    assert result["attempts"] == 2


@respx.mock
@pytest.mark.asyncio
async def test_deliver_all_retries_fail(wh: WebhookDelivery):
    """All retries exhausted should go to dead letter."""
    route = respx.post("http://hook.example.com")
    route.mock(side_effect=httpx.ConnectError("always down"))
    result = await wh.deliver(
        "http://hook.example.com", {"event": "test"}, max_retries=2, retry_delay=0.01
    )
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
    route = respx.post("http://hook.example.com")
    route.mock(return_value=httpx.Response(200, json={"ok": True}))

    await wh.deliver("http://hook.example.com", {"event": "test"})

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
    route = respx.post("http://hook.example.com")
    route.mock(return_value=httpx.Response(200, json={"ok": True}))

    await wh.deliver("http://hook.example.com", {"event": "test"}, event_type="custom.event")
    assert route.calls[0].request.headers["X-Pry-Event"] == "custom.event"


# ---------------------------------------------------------------------------
# Edge: missing signing secret
# ---------------------------------------------------------------------------


def test_init_empty_secret(tmp_path: Path):
    with (
        patch("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "webhooks2"),
        patch("pry.api.webhook_delivery.settings.webhook_secret", ""),
    ):
        w = WebhookDelivery()
        assert w.signing_secret == ""  # empty key allowed at init, but see below
        assert w.secret_configured is False


@respx.mock
@pytest.mark.asyncio
async def test_deliver_empty_secret_refused(tmp_path: Path):
    """FAIL-CLOSED: no signing secret => delivery refused, nothing sent.

    An HMAC with an empty key is forgeable by anyone, so delivering a
    'signed' webhook would give receivers false integrity guarantees.
    """
    with (
        patch("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "webhooks3"),
        patch("pry.api.webhook_delivery.settings.webhook_secret", ""),
    ):
        w = WebhookDelivery()
        route = respx.post("http://hook.example.com")
        route.mock(return_value=httpx.Response(200, json={"ok": True}))
        result = await w.deliver("http://hook.example.com", {"event": "test"})
        assert result["success"] is False
        assert result.get("refused") is True
        assert "secret" in result["error"].lower()
        assert route.call_count == 0  # nothing left the process unsigned


def test_sign_payload_empty_secret_raises(tmp_path: Path):
    with (
        patch("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "webhooks4"),
        patch("pry.api.webhook_delivery.settings.webhook_secret", ""),
    ):
        w = WebhookDelivery()
        with pytest.raises(WebhookSecretNotConfigured):
            w.sign_payload({"event": "test"})


def test_secret_configured_property(tmp_path: Path):
    with patch("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "webhooks5"):
        configured = WebhookDelivery(signing_secret="real-secret")
        assert configured.secret_configured is True
