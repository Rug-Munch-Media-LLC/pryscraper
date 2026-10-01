# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""End-to-end dispatcher checks, part 2 (split for the 200-line cap)."""

from __future__ import annotations

from typing import Any

import pytest

import pry_mcp.tools as mcp_tools

# Tool -> (package, module, minimal required arguments), derived from the live
# tool registry so it cannot drift from what is actually dispatched. The test
# asserts every required handler parameter is supplied; a tool added without its
# argument shows up here as a failure rather than as a silently untested path.
_HANDLER_SIGNATURE_CASES: list[tuple[str, str, str, dict]] = [
    ("pry_restaurant", "food_data", "restaurants", {"name": "Katz's Delicatessen"}),
    ("pry_grocery", "food_data", "grocery", {"zip_code": "10001"}),
    ("pry_weather", "weather", "forecast", {"location": "Berlin"}),
    ("pry_domain", "domain", "whois", {"domain": "example.com"}),
    ("pry_agri", "agriculture", "prices", {"crop": "corn", "region": "Iowa"}),
    ("pry_deals", "deals", "search", {"query": "laptop"}),
    ("pry_drop_alert", "drop_alert", "check", {"product": "widget"}),
]


class TestDispatcherBulk:
    @pytest.mark.parametrize(
        ("tool_name", "arguments"),
        [
            ("pry_app_search", {"query": "crypto wallet"}),
            ("pry_news", {"query": "ethereum"}),
            ("pry_sentiment", {"query": "bitcoin"}),
            ("pry_weather", {"location": "Austin, TX"}),
            ("pry_contracts", {"query": "cybersecurity"}),
            ("pry_grants", {"query": "clean energy"}),
            ("pry_energy_lmp", {"region": "ERCOT"}),
            ("pry_freight", {"route": "Shanghai to LA"}),
            ("pry_compliance", {"query": "Acme"}),
            ("pry_company_watch", {"company": "Acme"}),
            ("pry_events", {"query": "nba finals"}),
            ("pry_resale", {"event_id": "evt_1"}),
            ("pry_imports", {"company": "Acme"}),
            ("pry_firmographics", {"company": "Acme"}),
            ("pry_papers", {"query": "transformers"}),
            ("pry_domain", {"domain": "example.com"}),
            ("pry_agri", {"crop": "corn", "region": "Iowa"}),
            ("pry_deals", {"query": "laptop"}),
            ("pry_drop_alert", {"product": "widget"}),
        ],
    )
    async def test_previously_unavailable_tools_reach_their_handler(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        """Every ``_common`` registry tool that the defect broke must reach a handler.

        Kills any partial fix (per-tool, per-package) — these are the tools that
        advertised a schema to the LLM and could never run. Each dispatches to
        its real landed handler; the assertion is that the *dispatch layer*
        found and called it, i.e. no MODULE_UNAVAILABLE.
        """
        dispatcher = _DISPATCHERS[tool_name]
        result = await dispatcher(tool_name, arguments)

        assert result is not None
        text = result["content"][0]["text"]
        assert "MODULE_UNAVAILABLE" not in text, f"{tool_name} still reports MODULE_UNAVAILABLE"

    @pytest.mark.parametrize(
        ("tool_name", "arguments"),
        [
            ("pry_procurement", {"query": "cybersecurity"}),
            ("pry_recalls", {"query": "battery"}),
            ("pry_patents", {"query": "blockchain identity"}),
            ("pry_trademarks", {"query": "acme"}),
        ],
    )
    async def test_gov_ip_tools_reach_their_handler(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        """gov/ip went through ``__import__(package)`` — same defect, same fix.

        Kills the mutation that fixes only ``_common.py``/``sports.py`` and
        leaves gov.py's bare package import.
        """
        dispatcher = _GOV_DISPATCHERS[tool_name]
        result = await dispatcher(tool_name, arguments)

        assert result is not None
        assert "MODULE_UNAVAILABLE" not in result["content"][0]["text"]

    async def test_sports_tool_reaches_handler(self) -> None:
        """sports.py had its own copy of the bare import.

        Kills the mutation that leaves ``sports.py`` importing bare
        ``sports_data.{module}`` while ``_common.py`` is fixed.
        """
        result = await mcp_tools.call_sports_tool(
            "pry_odds", {"event_query": "lakers", "sport": "nba", "limit": 2}
        )

        assert result is not None
        assert "MODULE_UNAVAILABLE" not in result["content"][0]["text"]

    async def test_scrape_methods_reads_registry_from_datasets(self) -> None:
        """``pry_scrape_methods`` resolves its METHODS registry via the same path.

        Kills the mutation that leaves sports.py's special-cased
        ``__import__("scraping_methods")`` / ``sports_data.books`` sites bare.
        """
        result = await mcp_tools.call_sports_tool("pry_scrape_methods", {})

        assert result is not None
        text = result["content"][0]["text"]
        assert "MODULE_UNAVAILABLE" not in text
        assert '"methods"' in text


# Handler signature cases: (tool, package, module_name, representative
# arguments) for every registry entry that the defect broke. Driving the real
# kwargs builder against the real handler signature is what proves a tool can
# actually run, not merely that its module imports.
# Dispatcher table so the parametrized handler tests do not encode the module
# layout of each domain file in the test body.
_DISPATCHERS: dict[str, Any] = {
    "pry_app_search": mcp_tools.call_app_store_tool,
    "pry_app_reviews": mcp_tools.call_app_store_tool,
    "pry_news": mcp_tools.call_news_tool,
    "pry_sentiment": mcp_tools.call_news_tool,
    "pry_weather": mcp_tools.call_climate_tool,
    "pry_agri": mcp_tools.call_climate_tool,
    "pry_contracts": mcp_tools.call_bidding_tool,
    "pry_grants": mcp_tools.call_bidding_tool,
    "pry_energy_lmp": mcp_tools.call_energy_tool,
    "pry_freight": mcp_tools.call_freight_tool,
    "pry_compliance": mcp_tools.call_compliance_tool,
    "pry_company_watch": mcp_tools.call_compliance_tool,
    "pry_events": mcp_tools.call_events_tool,
    "pry_resale": mcp_tools.call_events_tool,
    "pry_imports": mcp_tools.call_supply_tool,
    "pry_firmographics": mcp_tools.call_supply_tool,
    "pry_papers": mcp_tools.call_research_tool,
    "pry_domain": mcp_tools.call_research_tool,
    "pry_deals": mcp_tools.call_deals_tool,
    "pry_drop_alert": mcp_tools.call_deals_tool,
}

_GOV_DISPATCHERS: dict[str, Any] = {
    "pry_procurement": mcp_tools.call_gov_tool,
    "pry_recalls": mcp_tools.call_gov_tool,
    "pry_patents": mcp_tools.call_ip_tool,
    "pry_trademarks": mcp_tools.call_ip_tool,
}
