# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Layer 4: structuredContent must satisfy the declared outputSchema.

Regression for the 2026-10-23 contract audit: five Pry tools advertised an
outputSchema that contradicted the payload they returned, so a schema-validating
client rejected successful calls or read fields (``data.content``,
``data.cuisine``) that never existed. Each case drives the real MCP server
through ``tools/call`` and checks the emitted ``structuredContent`` both ways.
Payloads are the live shapes captured on 2026-10-23.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pry_mcp import PRY_TOOLS

from ._contract import validate_payload
from ._support import _call, _fake_module, _patch_module, _server

TOOLS = {t["name"]: t for t in PRY_TOOLS}

SCRAPE = {
    "success": True,
    "data": {
        "markdown": "This domain is for use in documentation examples.",
        "metadata": {
            "url": "https://example.net",
            "method": "cloudscraper",
            "title": "Example Domain",
            "description": "",
            "markdown_quality": 100,
            "formats": ["markdown"],
            "offset": 0,
            "total": 156,
        },
    },
    "_cached": True,
}
CRAWL = {
    "success": True,
    "data": {
        "id": "sync",
        "url": "https://example.net",
        "pages": [
            {
                "url": "https://example.net",
                "markdown": "body",
                "title": "Example",
                "method": "cloudscraper",
            }
        ],
    },
}
TEMPLATE = {
    "success": True,
    "data": {
        "template_id": "abcnews-article",
        "template_name": "ABC News Article",
        "url": "https://abcnews.go.com/",
        "items": [],
        "count": 0,
        "extracted_at": "2026-10-23T10:21:45+00:00",
        "warning": "No items matched.",
    },
}
LMP = [
    {
        "region": "nyiso",
        "node": "CAPITL",
        "timestamp": "2026-08-15T04:00:00+00:00",
        "price_usd_mwh": 42.97,
        "lmp_type": "DAM",
    }
]
RESTAURANT = {
    "restaurant": "Test",
    "location": "",
    "menu": [{"item": "CMP", "price": 30, "description": None, "category": "Menu"}],
    "source": "https://example.test/menu",
}


def _rest_client(payload: dict[str, Any]) -> MagicMock:
    """httpx-client stand-in returning ``payload`` for any request."""
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.request = AsyncMock(return_value=response)
    return client


def _proxied(name: str, args: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    client = _rest_client(payload)
    with patch("pry_mcp.fallback_server.get_client", AsyncMock(return_value=client)):
        return asyncio.run(_call(_server(), name, args))["result"]


def _assert_contract(name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Assert the call produced structuredContent that honours outputSchema."""
    assert not result.get("isError"), f"{name}: call failed: {result.get('content')}"
    payload = result.get("structuredContent")
    assert payload is not None, f"{name}: no structuredContent despite declaring outputSchema"
    blocks = [b for b in result.get("content", []) if b.get("type") == "text"]
    assert json.loads(blocks[0]["text"]) == payload, (
        f"{name}: text body disagrees with structuredContent"
    )
    validate_payload(payload, TOOLS[name]["outputSchema"])
    return payload


class TestRestRoutedContract:
    """Tools proxied to the Pry REST API."""

    @pytest.mark.parametrize(
        ("name", "args", "payload"),
        [
            ("pry_scrape", {"url": "https://example.net"}, SCRAPE),
            ("pry_crawl", {"url": "https://example.net"}, CRAWL),
            ("pry_template", {"template_id": "abcnews-article", "url": "https://x.test"}, TEMPLATE),
        ],
    )
    def test_payload_honours_output_schema(self, name: str, args: dict, payload: dict) -> None:
        assert _assert_contract(name, _proxied(name, args, payload)) == payload

    def test_scrape_field_is_markdown_not_content(self) -> None:
        data = _assert_contract(
            "pry_scrape", _proxied("pry_scrape", {"url": "https://e.net"}, SCRAPE)
        )
        assert data["data"]["markdown"]
        assert "content" not in data["data"]

    def test_template_failure_omits_data(self) -> None:
        failure = {"success": False, "error": "Template not found: nope"}
        args = {"template_id": "nope", "url": "https://e.net"}
        payload = _assert_contract("pry_template", _proxied("pry_template", args, failure))
        assert payload["success"] is False


class TestLocalDispatchContract:
    """Tools resolved by the in-process domain dispatchers."""

    def _local(
        self, name: str, args: dict[str, Any], module: str, fn: str, returns: Any
    ) -> dict[str, Any]:
        """Call ``name`` with the domain handler ``module.fn`` stubbed to ``returns``."""
        fake = _fake_module(**{fn: AsyncMock(return_value=returns)})
        with _patch_module(module, fake):
            return _assert_contract(name, asyncio.run(_call(_server(), name, args))["result"])

    def test_energy_lmp_returns_a_list(self) -> None:
        payload = self._local(
            "pry_energy_lmp", {"region": "CAISO"}, "datasets.energy_data.lmp", "get_lmp", LMP
        )
        assert isinstance(payload["data"], list)
        assert payload["data"][0]["price_usd_mwh"] == 42.97

    def test_energy_lmp_empty_list_is_valid(self) -> None:
        payload = self._local(
            "pry_energy_lmp", {"region": "CAISO"}, "datasets.energy_data.lmp", "get_lmp", []
        )
        assert payload["data"] == []

    def test_restaurant_menu_shape(self) -> None:
        payload = self._local(
            "pry_restaurant",
            {"name": "Test"},
            "datasets.food_data.restaurants",
            "get_restaurant_menu",
            RESTAURANT,
        )
        assert payload["data"]["restaurant"] == "Test"
        assert isinstance(payload["data"]["menu"], list)
        assert "sections" not in payload["data"]
