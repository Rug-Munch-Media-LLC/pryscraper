"""PRY_API_KEY auth gating on protected endpoints."""

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
    client_auth,
)


class TestAuth:
    """PRY_API_KEY gating on protected endpoints."""

    def test_health_is_public(self, client_auth: TestClient) -> None:
        """Health endpoints should not require auth."""
        resp = client_auth.get("/health")
        assert resp.status_code in (200, 503)

    def test_scrape_requires_auth(self, client_auth: TestClient) -> None:
        """Scraping endpoints require valid Bearer token when api_key is set."""
        resp = client_auth.post(
            "/v1/scrape",
            json={"url": "https://example.com"},
        )
        assert resp.status_code == 401

    def test_scrape_with_valid_auth(self, client_auth: TestClient) -> None:
        """Valid Bearer token should pass auth."""
        resp = client_auth.post(
            "/v1/scrape",
            json={"url": "https://example.com"},
            headers={"authorization": "Bearer test-api-key"},
        )
        assert resp.status_code == 200

    def test_scrape_with_wrong_auth(self, client_auth: TestClient) -> None:
        """Wrong Bearer token should get 401."""
        resp = client_auth.post(
            "/v1/scrape",
            json={"url": "https://example.com"},
            headers={"authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401
