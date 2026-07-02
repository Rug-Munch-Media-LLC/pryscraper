# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for API helpers."""

from api import _get_or_key


def test_get_or_key_from_env(monkeypatch) -> None:
    monkeypatch.setattr("api.settings.openrouter_api_key", "sk-test-key-123")
    key = _get_or_key()
    assert key == "sk-test-key-123"


def test_get_or_key_empty_when_not_set(monkeypatch) -> None:
    monkeypatch.setattr("api.settings.openrouter_api_key", "")
    monkeypatch.setattr("os.path.isfile", lambda p: False)
    key = _get_or_key()
    assert key is None


def test_vision_models_fallback_list() -> None:
    from api import VISION_MODELS_FALLBACK

    assert len(VISION_MODELS_FALLBACK) >= 3
    assert all("free" in m for m in VISION_MODELS_FALLBACK)
