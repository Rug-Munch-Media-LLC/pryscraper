# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT.
"""Tests for API helpers and auth."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app
from pry.core.settings import settings


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_get_or_key_from_env(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-test-key-123")
    from routers.vision import _get_or_key

    key = _get_or_key()
    assert key == "sk-test-key-123"


def test_get_or_key_empty_when_not_set(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr("os.path.isfile", lambda p: False)
    from routers.vision import _get_or_key

    key = _get_or_key()
    assert key is None


def test_vision_models_fallback_list() -> None:
    from routers.vision import VISION_MODELS_FALLBACK

    assert len(VISION_MODELS_FALLBACK) >= 3
    assert all("free" in m for m in VISION_MODELS_FALLBACK)


@pytest.mark.asyncio
async def test_api_key_required_when_set(client: TestClient, monkeypatch) -> None:
    """Protected endpoints require a valid Bearer PRY_API_KEY."""
    monkeypatch.setattr(settings, "api_key", "secret-pry-key")
    # Disable x402 payment gating so we can test auth in isolation.
    with patch(
        "pry.misc.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        resp = client.post("/v1/scrape", json={"url": "https://example.com"})
    assert resp.status_code == 401

    with patch(
        "pry.misc.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        resp = client.post(
            "/v1/scrape",
            json={"url": "https://example.com"},
            headers={"authorization": "Bearer wrong-key"},
        )
    assert resp.status_code == 401

    with patch(
        "pry.misc.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        resp = client.post(
            "/v1/scrape",
            json={"url": "https://example.com"},
            headers={"authorization": "Bearer secret-pry-key"},
        )
    # auth passes; endpoint returns 402 because we did not mock scraper, which is fine
    assert resp.status_code in (200, 402)
