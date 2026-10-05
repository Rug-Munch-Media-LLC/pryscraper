# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Merged round-trip tables and their coverage guard."""

from __future__ import annotations

from typing import Any

from pry_mcp.tools import PRY_TOOL_NAMES

from ._tables_domain_a import DOMAIN_TOOLS_A
from ._tables_domain_b import DOMAIN_TOOLS_B
from ._tables_domain_c import DOMAIN_TOOLS_C

_DOMAIN_TOOLS: dict[str, tuple[str, tuple[str, ...], dict[str, Any]]] = {
    **DOMAIN_TOOLS_A,
    **DOMAIN_TOOLS_B,
    **DOMAIN_TOOLS_C,
}

# REST-proxy tools: name -> sample arguments. The fallback server calls the
# Pry HTTP API via httpx; tests mock httpx.AsyncClient so no network is used.
_REST_PROXY_TOOLS: dict[str, dict[str, Any]] = {
    "pry_scrape": {"url": "https://example.com"},
    "pry_crawl": {"url": "https://example.com", "max_pages": 5},
    "pry_extract": {
        "url": "https://example.com/products",
        "schema": {
            "name": "product",
            "fields": [{"name": "price", "selector": ".price", "type": "text"}],
        },
    },
    "pry_template": {
        "template_id": "amazon-product",
        "url": "https://www.amazon.com/dp/B08N5WRWNW",
    },
    "pry_search_templates": {"q": "amazon"},
    "pry_monitor": {"name": "price watch", "url": "https://example.com/pricing"},
    "pry_enrich": {"url": "https://startup.example.com"},
    "pry_parse_document": {"url": "https://example.com/spec.pdf"},
    "pry_screenshot": {"url": "https://example.com/checkout"},
    "pry_x402_pricing": {},
    "pry_balance": {"api_key": "pry_deadbeef_" + "0" * 32},
    "pry_buy_pack": {"pack_id": "starter"},
    "pry_referrals": {"category": "proxies"},
    "pry_scrape_methods": {},
}

# Local actor-parity tools: name -> sample arguments. Executed through
# call_actor_tool with a mocked UltimateScraper (no network) - same code
# path as tests/test_mcp_actor_parity.py.
_LOCAL_ACTOR_TOOLS: dict[str, dict[str, Any]] = {
    "pry_actor_catalog": {"domain": "monitor"},
    "pry_actor_run": {"actor": "universal-scraper", "urls": ["https://example.com"]},
}

# Guard: the tables must cover every registered tool, or the audit is broken.
assert set(_DOMAIN_TOOLS) | set(_REST_PROXY_TOOLS) | set(_LOCAL_ACTOR_TOOLS) == set(
    PRY_TOOL_NAMES
), "round-trip tables do not cover every PRY_TOOLS entry"
