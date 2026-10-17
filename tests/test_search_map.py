# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Tests for the Firecrawl-parity ``/v1/search`` and ``/v1/map`` routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app

if TYPE_CHECKING:
    from collections.abc import Iterator

MODULE = "pry.api.routers.scraping.search_map"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient with the x402 gate bypassed (functional tests only)."""
    with patch(
        "pry.payments.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        yield TestClient(app)


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


def test_search_returns_result_shape(client: TestClient) -> None:
    payload = {
        "results": [
            {"url": "https://example.com/a", "title": "A", "snippet": "first"},
            {"url": "https://example.com/b", "title": "B", "snippet": "second"},
        ]
    }
    with patch(f"{MODULE}.search_web", AsyncMock(return_value=payload)):
        response = client.post("/v1/search", json={"query": "pry api", "limit": 2})

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["query"] == "pry api"
    expected = [
        {"url": "https://example.com/a", "title": "A", "description": "first"},
        {"url": "https://example.com/b", "title": "B", "description": "second"},
    ]
    assert body["results"] == expected


def test_map_returns_deduped_same_origin_links(client: TestClient) -> None:
    sitemap = """<?xml version="1.0"?><urlset>
        <url><loc>https://example.com/a</loc></url>
        <url><loc>https://example.com/a#section</loc></url>
        <url><loc>https://example.com/b</loc></url>
        <url><loc>https://other.example/x</loc></url>
    </urlset>"""
    with (
        patch(f"{MODULE}.validate_url_async", AsyncMock(side_effect=lambda u: u)),
        patch(f"{MODULE}.safe_get", AsyncMock(return_value=_FakeResponse(sitemap))),
    ):
        response = client.post("/v1/map", json={"url": "https://example.com", "limit": 50})

    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://example.com"
    assert body["count"] == 2
    expected = [
        {"url": "https://example.com/a"},
        {"url": "https://example.com/b"},
    ]
    assert body["links"] == expected


def test_search_limit_cap_enforced(client: TestClient) -> None:
    response = client.post("/v1/search", json={"query": "x", "limit": 21})
    assert response.status_code == 422


def test_map_limit_cap_enforced(client: TestClient) -> None:
    response = client.post("/v1/map", json={"url": "https://example.com", "limit": 501})
    assert response.status_code == 422


def test_unpaid_search_returns_402() -> None:
    # No bypass fixture: the x402 middleware must issue the challenge.
    response = TestClient(app).post("/v1/search", json={"query": "x", "limit": 1})
    assert response.status_code == 402


def test_unpaid_map_returns_402() -> None:
    response = TestClient(app).post("/v1/map", json={"url": "https://example.com", "limit": 1})
    assert response.status_code == 402


def test_routes_present_in_openapi() -> None:
    schema = app.openapi()
    assert "/v1/search" in schema["paths"]
    assert "/v1/map" in schema["paths"]
