"""Error shapes and CORS behaviour of the Pry API."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api_integration_support import (  # noqa: F401 — fixtures for this module
    _mock_all_deps,
    client,
)


class TestErrorHandling:
    """API returns consistent error shapes for HTTP errors."""

    def test_404_returns_json(self, client: TestClient) -> None:
        resp = client.get("/nonexistent-route-12345")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body

    def test_405_on_wrong_method(self, client: TestClient) -> None:
        resp = client.get("/v1/scrape")
        assert resp.status_code == 405

    def test_422_on_invalid_json(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/scrape", content=b"not-json", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 422


class TestCORS:
    """CORS middleware should set broad allow-origin."""

    def test_cors_headers_present(self, client: TestClient) -> None:
        # Preflight must NOT be gated by auth or the x402 paywall: browsers send
        # OPTIONS before the real request and expect a 200 with allow headers.
        resp = client.options(
            "/v1/scrape",
            headers={
                "Origin": "https://app.rugmunch.io",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 200
        headers = resp.headers
        assert headers.get("access-control-allow-origin") == "https://app.rugmunch.io"
        assert "POST" in headers.get("access-control-allow-methods", "")

    def test_cors_disallowed_origin_rejected(self, client: TestClient) -> None:
        resp = client.options(
            "/v1/scrape",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 400
