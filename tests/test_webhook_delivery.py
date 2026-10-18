# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for webhook_delivery.py — init, HMAC signing, delivery log and dead letters."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from pry.api.webhook_delivery import WebhookDelivery

if TYPE_CHECKING:
    from pathlib import Path

import pytest

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


def test_init_creates_dirs(wh: WebhookDelivery, tmp_path: Path):
    assert (tmp_path / "webhooks").exists()


def test_init_signing_secret_resolution(monkeypatch):
    """Should use explicit secret over env over settings."""
    w = WebhookDelivery(signing_secret="explicit")
    assert w.signing_secret == "explicit"


def test_init_falls_to_settings(monkeypatch):
    monkeypatch.delenv("PRY_WEBHOOK_SECRET", raising=False)
    with patch("pry.api.webhook_support.settings.webhook_secret", "from-settings"):
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
    wh._dead_letter({"k": "v"}, "http://x.com", "r")
    dead = wh.get_dead_letter()
    assert dead[0]["payload"] == {"k": "v"}
    assert dead[0]["reason"] == "r"


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
