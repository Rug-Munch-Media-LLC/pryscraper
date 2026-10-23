# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Layer 5: tool definitions must describe a call that can actually succeed.

Three tools declared an input schema the handler could not be driven by:
``pry_historical_odds`` never exposed the ``event_id`` its handler requires,
``pry_betting_percentages`` left that argument optional, and
``pry_kelly_criterion`` advertised a ``bankroll`` default the handler does not
apply — all three failed server-side. ``pry_mega_search`` returned its engine
envelope at the top level while declaring it under ``data``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, ClassVar
from unittest.mock import AsyncMock

from pry_mcp import PRY_TOOLS

from ._contract import validate_payload
from ._support import _call, _fake_module, _patch_module, _server

TOOLS = {t["name"]: t for t in PRY_TOOLS}


def _required(name: str) -> list[str]:
    return TOOLS[name]["inputSchema"].get("required", [])


def _props(name: str) -> dict[str, Any]:
    return TOOLS[name]["inputSchema"]["properties"]


class TestRequiredArguments:
    """Every argument the handler demands must be required in the schema."""

    def test_historical_odds_exposes_event_id(self) -> None:
        assert "event_id" in _props("pry_historical_odds")
        assert "event_id" in _required("pry_historical_odds")

    def test_betting_percentages_requires_the_event(self) -> None:
        # ``event`` is mapped onto the handler's required ``event_id``.
        assert "event" in _required("pry_betting_percentages")

    def test_kelly_requires_bankroll_and_promises_no_default(self) -> None:
        assert "bankroll" in _required("pry_kelly_criterion")
        assert "default" not in _props("pry_kelly_criterion")["bankroll"]


class TestMegaSearchEnvelope:
    """mega_search emits its envelope unwrapped; the schema must say so."""

    PAYLOAD: ClassVar[dict[str, Any]] = {
        "results": [
            {
                "url": "https://example.test/",
                "title": "Example",
                "snippet": "An example result",
                "consensus": 2,
                "sources": ["duckduckgo", "mojeek"],
            }
        ],
        "total": 1,
        "query": "example",
        "engines": {"duckduckgo": "ok"},
        "engines_ok": ["duckduckgo", "mojeek"],
        "engines_failed": [],
    }

    def test_declares_no_data_wrapper(self) -> None:
        assert "data" not in TOOLS["pry_mega_search"]["outputSchema"]["properties"]

    def test_payload_honours_output_schema(self) -> None:
        module = _fake_module(mega_search=AsyncMock(return_value=self.PAYLOAD))
        with _patch_module("pry.engine.mega_search", module):
            result = asyncio.run(_call(_server(), "pry_mega_search", {"query": "example"}))[
                "result"
            ]
        assert not result.get("isError"), result.get("content")
        payload = result["structuredContent"]
        assert json.loads(result["content"][0]["text"]) == payload
        module.mega_search.assert_awaited_once()
        assert isinstance(payload["results"], list)
        validate_payload(payload, TOOLS["pry_mega_search"]["outputSchema"])
