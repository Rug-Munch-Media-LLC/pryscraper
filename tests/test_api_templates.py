# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT.
"""End-to-end tests for the templates router endpoints."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pry.api.api import app


@pytest.fixture(autouse=True)
def bypass_x402_middleware() -> Iterator[None]:
    """Disable x402 payment gating for template execution tests."""
    with patch(
        "pry.payments.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.asyncio
async def test_list_templates(client: TestClient) -> None:
    templates = [
        {"id": "amazon_product", "name": "Amazon Product", "category": "ecommerce"},
        {"id": "github_repo", "name": "GitHub Repo", "category": "dev"},
    ]
    with patch("pry.api.routers.templates.list_templates", return_value=templates):
        resp = client.get("/v1/templates")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["total"] == 2
    assert "ecommerce" in data["data"]["categories"]


@pytest.mark.asyncio
async def test_get_template(client: TestClient) -> None:
    template = {"id": "amazon_product", "name": "Amazon Product"}
    with patch("pry.api.routers.templates.get_template", return_value=template):
        resp = client.get("/v1/templates/amazon_product")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["id"] == "amazon_product"


@pytest.mark.asyncio
async def test_get_template_not_found(client: TestClient) -> None:
    with patch("pry.api.routers.templates.get_template", return_value=None):
        resp = client.get("/v1/templates/missing")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_execute_template(client: TestClient) -> None:
    result = {"success": True, "data": {"title": "Widget"}}
    with patch("pry.api.routers.templates.execute_template", new=AsyncMock(return_value=result)):
        resp = client.post(
            "/v1/templates/execute",
            json={"template_id": "amazon_product", "url": "https://example.com"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["title"] == "Widget"


@pytest.mark.asyncio
async def test_batch_execute_templates(client: TestClient) -> None:
    result = {"success": True, "data": {"title": "Widget"}}
    items = [
        {"template_id": "amazon_product", "url": "https://example.com/1"},
        {"template_id": "github_repo", "url": "https://example.com/2"},
    ]
    with patch("pry.api.routers.templates.execute_template", new=AsyncMock(return_value=result)):
        resp = client.post("/v1/templates/batch", json=items)

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["total"] == 2
    assert data["data"]["failed"] == 0
    assert data["data"]["results"][0]["template_id"] == "amazon_product"


@pytest.mark.asyncio
async def test_batch_execute_templates_limits_size(client: TestClient) -> None:
    items = [{"template_id": "t", "url": "https://example.com"} for _ in range(21)]
    resp = client.post("/v1/templates/batch", json=items)

    assert resp.status_code == 400
