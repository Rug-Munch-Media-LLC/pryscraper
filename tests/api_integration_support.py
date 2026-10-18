"""Shared fixtures for the Pry API HTTP integration tests.

Split out of ``test_api_integration.py`` so each sibling module owns one
subject and stays under the 200-line file gate. Importing a fixture into a
test module registers it there, so the autouse dependency mock still applies
per module.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pry.core.settings import settings

if TYPE_CHECKING:
    from collections.abc import Iterator


def _has_postgres(host: str = "127.0.0.1", port: int = 5432) -> bool:
    """Return True if Postgres is reachable on the given host:port.

    Used to skip integration tests that require a live database when running
    the suite locally without docker-compose up.
    """
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex((host, port)) == 0
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _mock_all_deps() -> Iterator[None]:
    """Mock all external deps so no real scraping/parsing occurs."""
    scraper_mock = MagicMock()
    scraper_mock.scrape = AsyncMock(
        return_value={
            "status": "ok",
            "url": "https://example.com",
            "content": "# Mocked content",
            "raw_html": "<html><body>Mocked</body></html>",
            "method": "direct",
        }
    )
    scraper_mock.crawl = AsyncMock(return_value=[{"url": "https://example.com", "status": "ok"}])
    # Contract: Scraper.map_urls() -> list[str] (same-origin URLs).
    scraper_mock.map_urls = AsyncMock(
        return_value=["https://example.com/page1", "https://example.com/page2"]
    )
    scraper_mock.detect_block = AsyncMock(
        return_value={
            "detected": True,
            "type": "cloudflare",
            "confidence": 0.95,
        }
    )

    extractor_mock = MagicMock()
    extractor_mock.extract = AsyncMock(
        return_value={
            "success": True,
            "data": {"product_name": "Widget Pro", "price": "$29.99"},
        }
    )

    parser_mock = MagicMock()
    parser_mock.parse = AsyncMock(
        return_value={
            "success": True,
            "data": {"title": "Test", "body": "Content"},
        }
    )

    cache_mock = MagicMock()
    cache_mock.get = MagicMock(return_value=None)
    cache_mock.set = MagicMock()

    advanced_mock = MagicMock()
    advanced_mock.extract = AsyncMock(
        return_value={
            "success": True,
            "data": {"name": "Widget Pro", "price": 29.99},
        }
    )

    with (
        patch.multiple(
            "pry.core.deps",
            scraper=scraper_mock,
            extractor=extractor_mock,
            parser=parser_mock,
            cache=cache_mock,
            advanced=advanced_mock,
        ),
        patch(
            # The `/v1/map` handler resolves ``scraper`` through the scraping
            # router module, which bound the object at import time — patching
            # ``pry.core.deps`` alone leaves that binding pointing at the real
            # scraper, so the mock never reached the endpoint.
            "pry.api.routers.scraping.scraping.scraper",
            scraper_mock,
        ),
    ):
        yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient with x402 middleware bypassed (it would require payment)."""
    from pry.api.api import app

    with (
        patch(
            "pry.payments.x402_middleware.X402Middleware.__call__",
            lambda self, scope, receive, send: self.app(scope, receive, send),
        ),
        TestClient(app) as c,
    ):
        yield c


@pytest.fixture
def client_auth(client: TestClient, monkeypatch) -> TestClient:
    """TestClient with PRY_API_KEY set (auth required)."""
    monkeypatch.setattr(settings, "api_key", "test-api-key")
    return client
