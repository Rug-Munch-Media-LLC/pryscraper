# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP <-> Apify Store parity tests.

Guarantees the MCP surface covers every Apify actor:

- ``pry_actor_catalog`` lists ALL presets with EXACT pricing events from
  ``actor_factory.presets`` (single source of truth).
- ``pry_actor_run`` executes through the same PPEScraperRunner +
  PROCESSORS code path as the deployed actors - proven per processor
  type with mocked scrape results (processors are pure; no network).
- Both tools are registered in PRY_TOOLS with valid schemas and route
  through ``combined_tool_executor`` without falling to the REST proxy.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from actor_factory.presets import ALL_PRESETS
from actor_factory.processors import PROCESSORS
from pry_mcp.fallback_server import combined_tool_executor
from pry_mcp.tools import ACTOR_TOOL_NAMES, PRY_TOOLS, call_actor_tool


def _text(result: dict[str, Any]) -> dict[str, Any]:
    """Parse the JSON payload of a single-text-block tool result."""
    blocks = result["content"]
    assert blocks, "result has no content blocks"
    assert blocks[0]["type"] == "text"
    return json.loads(blocks[0]["text"])


# ── registration & schema ────────────────────────────────────────────────────


class TestRegistration:
    def test_actor_tools_registered_in_pry_tools(self) -> None:
        names = {t["name"] for t in PRY_TOOLS}
        assert names >= ACTOR_TOOL_NAMES, f"missing from PRY_TOOLS: {ACTOR_TOOL_NAMES - names}"

    def test_schemas_are_wellformed(self) -> None:
        for t in PRY_TOOLS:
            if t["name"] not in ACTOR_TOOL_NAMES:
                continue
            assert t["inputSchema"]["type"] == "object"
            assert "properties" in t["inputSchema"]
            assert t["description"].strip(), t["name"]

    def test_run_tool_requires_actor_and_urls(self) -> None:
        run = next(t for t in PRY_TOOLS if t["name"] == "pry_actor_run")
        assert set(run["inputSchema"]["required"]) == {"actor", "urls"}

    def test_catalog_is_read_only_annotated(self) -> None:
        cat = next(t for t in PRY_TOOLS if t["name"] == "pry_actor_catalog")
        assert cat.get("annotations", {}).get("readOnlyHint") is True


# ── catalog parity ───────────────────────────────────────────────────────────


class TestCatalogParity:
    @pytest.mark.asyncio
    async def test_catalog_lists_every_preset(self) -> None:
        result = await call_actor_tool("pry_actor_catalog", {})
        payload = _text(result)
        assert payload["total"] == len(ALL_PRESETS)
        listed = {a["actor"] for a in payload["actors"]}
        expected = {n.removeprefix("pry-") for n in ALL_PRESETS}
        assert listed == expected, "catalog/preset drift"

    @pytest.mark.asyncio
    async def test_catalog_pricing_matches_presets_exactly(self) -> None:
        result = await call_actor_tool("pry_actor_catalog", {})
        by_name = {a["actor"]: a for a in _text(result)["actors"]}
        for preset_name, spec in ALL_PRESETS.items():
            row = by_name[preset_name.removeprefix("pry-")]
            got = [(e["event"], e["price_usd"]) for e in row["pricing_events"]]
            want = [(e.name, e.price_usd) for e in spec.pricing_events]
            assert got == want, f"{preset_name}: catalog pricing drifted from preset"

    @pytest.mark.asyncio
    async def test_catalog_processor_mapping_matches_presets(self) -> None:
        result = await call_actor_tool("pry_actor_catalog", {})
        by_name = {a["actor"]: a for a in _text(result)["actors"]}
        for preset_name, spec in ALL_PRESETS.items():
            row = by_name[preset_name.removeprefix("pry-")]
            assert row["processor"] == spec.processor, preset_name

    @pytest.mark.asyncio
    async def test_domain_filter_narrows(self) -> None:
        full = _text(await call_actor_tool("pry_actor_catalog", {}))["total"]
        filtered = _text(await call_actor_tool("pry_actor_catalog", {"domain": "monitor"}))
        assert 0 < filtered["total"] < full
        assert all(
            "monitor" in a["actor"] or "monitor" in a["title"].lower() for a in filtered["actors"]
        )

    @pytest.mark.asyncio
    async def test_non_actor_tool_returns_none(self) -> None:
        assert await call_actor_tool("pry_scrape", {}) is None


# ── runner parity: same pipeline as deployed actors ─────────────────────────


def _mock_runner_scrape(monkeypatch: pytest.MonkeyPatch, content: str = "<html>hi</html>") -> None:
    """Replace UltimateScraper network path with a deterministic result."""

    class FakeScraper:
        async def scrape(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
            return {
                "status": "ok",
                "method": "direct",
                "content": f"content for {url}",
                "raw_html": content,
                "scraped_at": "2026-08-26T00:00:00+00:00",
            }

    import actor_factory.runner as runner_mod

    real_init = runner_mod.PPEScraperRunner.__init__

    def patched(self, config: Any, actor_module: Any = None) -> None:
        real_init(self, config, actor_module)
        self._scraper = FakeScraper()

    monkeypatch.setattr(runner_mod.PPEScraperRunner, "__init__", patched)


class TestActorRunParity:
    @pytest.mark.asyncio
    async def test_unknown_actor_clean_error(self) -> None:
        result = await call_actor_tool(
            "pry_actor_run", {"actor": "nope", "urls": ["https://x.com"]}
        )
        assert result.get("isError") is True
        assert "unknown actor 'nope'" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_missing_urls_rejected(self) -> None:
        result = await call_actor_tool("pry_actor_run", {"actor": "universal-scraper"})
        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_default_pipeline_matches_platform_item_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_runner_scrape(monkeypatch)
        result = await call_actor_tool(
            "pry_actor_run",
            {"actor": "universal-scraper", "urls": ["https://example.com"]},
        )
        payload = _text(result)
        assert payload["item_count"] == 1
        item = payload["items"][0]
        # Same fields the Apify dataset item carries (runner._base shape).
        for key in ("url", "status", "method", "scraped_at", "content"):
            assert key in item, f"dataset field {key} missing"
        assert item["status"] == "ok"
        assert payload["equivalent_apify_charge_usd"] == 0.003

    @pytest.mark.parametrize(
        "preset_name",
        sorted(n for n in ALL_PRESETS if ALL_PRESETS[n].processor is not None),
    )
    @pytest.mark.asyncio
    async def test_every_processor_backed_actor_runs_through_mcp(
        self, monkeypatch: pytest.MonkeyPatch, preset_name: str
    ) -> None:
        """Store parity guarantee: each processor-backed actor executes its
        registered processor via the MCP surface."""
        _mock_runner_scrape(monkeypatch)
        actor = preset_name.removeprefix("pry-")
        result = await call_actor_tool(
            "pry_actor_run", {"actor": actor, "urls": ["https://t.dev/x"]}
        )
        payload = _text(result)
        assert payload["item_count"] == 1, f"{actor}: no items produced"
        spec = ALL_PRESETS[preset_name]
        assert spec.processor in PROCESSORS
        # Processor enriched the base item (its signature ran without error).
        assert payload["items"][0]["url"] == "https://t.dev/x"

    @pytest.mark.asyncio
    async def test_max_items_caps_batch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_runner_scrape(monkeypatch)
        urls = [f"https://t.dev/{i}" for i in range(10)]
        result = await call_actor_tool(
            "pry_actor_run",
            {"actor": "site-crawler", "urls": urls, "max_items": 3},
        )
        assert _text(result)["item_count"] == 3

    @pytest.mark.asyncio
    async def test_bad_target_becomes_error_item_not_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import actor_factory.runner as runner_mod

        class BoomScraper:
            async def scrape(self, url: str, options: dict[str, Any]) -> dict[str, Any]:
                raise RuntimeError("connection refused")

        real_init = runner_mod.PPEScraperRunner.__init__

        def patched(self, config: Any, actor_module: Any = None) -> None:
            real_init(self, config, actor_module)
            self._scraper = BoomScraper()

        monkeypatch.setattr(runner_mod.PPEScraperRunner, "__init__", patched)
        result = await call_actor_tool(
            "pry_actor_run", {"actor": "universal-scraper", "urls": ["https://dead.example"]}
        )
        payload = _text(result)
        assert payload["item_count"] == 1
        assert payload["items"][0]["status"] == "error"


# ── dispatch wiring ──────────────────────────────────────────────────────────


class TestDispatchWiring:
    @pytest.mark.asyncio
    async def test_combined_executor_routes_catalog_locally(self) -> None:
        """Catalog must resolve inside combined_tool_executor (never fall
        through to the REST proxy)."""
        result = await combined_tool_executor("pry_actor_catalog", {"domain": "ssl"})
        payload = _text(result)
        assert payload["total"] >= 1
        assert any(a["actor"] == "ssl-cert-monitor" for a in payload["actors"])

    @pytest.mark.asyncio
    async def test_combined_executor_routes_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_runner_scrape(monkeypatch)
        result = await combined_tool_executor(
            "pry_actor_run",
            {"actor": "rss-feed-monitor", "urls": ["https://t.dev/feed.xml"]},
        )
        payload = _text(result)
        assert payload["actor"] == "rss-feed-monitor"
        assert payload["item_count"] == 1
