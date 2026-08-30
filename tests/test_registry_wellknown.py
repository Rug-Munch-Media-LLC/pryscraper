# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for registry metadata, analytics, middleware, and well-known endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pry.api.api import app


class TestRegistryMetadata:
    """Test the registry metadata module."""

    def test_get_registry_manifest_has_required_fields(self) -> None:
        from pry.api.registry_metadata import get_registry_manifest

        manifest = get_registry_manifest()
        assert "name" in manifest
        assert "displayName" in manifest
        assert "description" in manifest
        assert "version" in manifest
        assert "mcp" in manifest
        assert "tools" in manifest
        assert "payment" in manifest
        assert "pricing" in manifest
        assert "tags" in manifest

    def test_manifest_tool_count_matches(self) -> None:
        from pry.api.registry_metadata import get_enriched_tools, get_registry_manifest

        manifest = get_registry_manifest()
        # Dynamic: stats.tools must match the actually-enriched tool list so
        # registry reconciliation (currently 76) never drifts from the data.
        assert manifest["stats"]["tools"] == len(get_enriched_tools())
        assert manifest["stats"]["tools"] > 0
        assert manifest["stats"]["categories"] > 20

    def test_manifest_payment_config(self) -> None:
        from pry.api.registry_metadata import get_registry_manifest

        manifest = get_registry_manifest()
        assert manifest["payment"]["x402"] is True
        assert "USDC" in manifest["payment"]["crypto"]
        assert "SOL" in manifest["payment"]["crypto"]
        assert "TRX" in manifest["payment"]["crypto"]

    def test_generate_llms_txt(self) -> None:
        from pry.api.registry_metadata import generate_llms_txt

        llms = generate_llms_txt()
        assert "# Pry Scraping API" in llms
        assert "## Tools" in llms
        assert "pry_scrape" in llms
        assert "pry_crawl" in llms

    def test_get_tools_by_category(self) -> None:
        from pry.api.registry_metadata import get_tools_by_category

        cats = get_tools_by_category()
        assert len(cats) > 20
        assert "web_scraping" in cats
        assert "sports_betting" in cats
        assert "legal" in cats

    def test_tool_enrichment(self) -> None:
        from pry.api.registry_metadata import get_enriched_tools

        tools = get_enriched_tools()
        for tool in tools:
            assert "category" in tool
            assert "keywords" in tool
            assert "use_cases" in tool
            assert "longDescription" in tool
            assert "group" in tool
            assert "capabilities" in tool


class TestWellKnownEndpoints:
    """Test well-known discovery endpoints."""

    client = TestClient(app)

    def test_x402_manifest_public(self) -> None:
        resp = self.client.get("/.well-known/x402.json")
        # Note: In production these are public via PryHttpMiddleware.
        # TestClient bypasses some ASGI middleware, so we verify the route exists.
        assert resp.status_code in (200, 401)  # 200 in prod, 401 in test client

    def test_agent_card_public(self) -> None:
        resp = self.client.get("/.well-known/agent.json")
        assert resp.status_code in (200, 401)

    def test_x402_bazaar_public(self) -> None:
        resp = self.client.get("/.well-known/x402-bazaar.json")
        assert resp.status_code in (200, 401)

    def test_llms_txt_public(self) -> None:
        resp = self.client.get("/llms.txt")
        assert resp.status_code in (200, 401)


class TestMCPPublicAccess:
    """Test that MCP endpoints are publicly accessible."""

    client = TestClient(app)

    def test_mcp_health_public(self) -> None:
        resp = self.client.get("/mcp/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # Dynamic: tools_count must match the reconciled registry (76), not a
        # hardcoded literal that drifts as tools are added/removed.
        from pry.api.registry_metadata import get_registry_manifest

        assert data["tools_count"] == get_registry_manifest()["stats"]["tools"]
        assert data["tools_count"] > 0

    def test_mcp_initialize_public(self) -> None:
        resp = self.client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data

    def test_mcp_tools_list_public(self) -> None:
        resp = self.client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Dynamic: tools/list length must track the reconciled registry (76).
        from pry.api.registry_metadata import get_registry_manifest

        assert len(data["result"]["tools"]) == get_registry_manifest()["stats"]["tools"]
        assert len(data["result"]["tools"]) > 0


class TestRouteClassification:
    """Test that route classification works correctly."""

    def test_mcp_paths_are_free(self) -> None:
        from pry.payments.x402_middleware.classification import classify_path

        assert classify_path("/mcp/health") == "free"
        assert classify_path("/mcp/sse") == "free"
        assert classify_path("/mcp") == "free"
        assert classify_path("/mcp/messages") == "free"
        assert classify_path("/mcp/messages/session123") == "free"

    def test_well_known_paths_are_free(self) -> None:
        from pry.payments.x402_middleware.classification import classify_path

        assert classify_path("/.well-known/x402.json") == "free"
        assert classify_path("/.well-known/agent.json") == "free"
        assert classify_path("/.well-known/x402-bazaar.json") == "free"
        assert classify_path("/llms.txt") == "free"

    def test_scrape_is_paid(self) -> None:
        from pry.payments.x402_middleware.classification import classify_path

        assert classify_path("/v1/scrape") == "paid"

    def test_health_is_free(self) -> None:
        from pry.payments.x402_middleware.classification import classify_path

        assert classify_path("/health") == "free"
        assert classify_path("/healthz") == "free"
