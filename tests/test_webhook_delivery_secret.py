# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for webhook_delivery.py — fail-closed behaviour without a signing secret."""

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

from pry.api.webhook_delivery import WebhookDelivery, WebhookSecretNotConfigured

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


# Edge: missing signing secret
# ---------------------------------------------------------------------------


def test_init_empty_secret(tmp_path: Path):
    with (
        patch("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "webhooks2"),
        patch("pry.api.webhook_support.settings.webhook_secret", ""),
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
        patch("pry.api.webhook_support.settings.webhook_secret", ""),
        patch(
            "pry.api.webhook_delivery._validate_url",
            side_effect=lambda url: (url, None),
        ),
    ):
        w = WebhookDelivery()
        route = respx.post("https://hook.example.com")
        route.mock(return_value=httpx.Response(200, json={"ok": True}))
        result = await w.deliver("https://hook.example.com", {"event": "test"})
        assert result["success"] is False
        assert result.get("refused") is True
        assert "secret" in result["error"].lower()
        assert route.call_count == 0  # nothing left the process unsigned


def test_sign_payload_empty_secret_raises(tmp_path: Path):
    with (
        patch("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "webhooks4"),
        patch("pry.api.webhook_support.settings.webhook_secret", ""),
    ):
        w = WebhookDelivery()
        with pytest.raises(WebhookSecretNotConfigured):
            w.sign_payload({"event": "test"})


def test_secret_configured_property(tmp_path: Path):
    with patch("pry.api.webhook_delivery.WEBHOOK_DIR", tmp_path / "webhooks5"):
        configured = WebhookDelivery(signing_secret="real-secret")
        assert configured.secret_configured is True
