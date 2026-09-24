"""Pry - MCP tool definitions (package).

PRY_TOOLS list with all scraper templates, aggregated from the
per-domain modules in this package. Split from the former
monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from . import (
    actions,
    actor,
    adaptive,
    appstore,
    attention,
    bidding,
    billing,
    climate,
    compliance,
    content_filter,
    crypto,
    data,
    deals,
    gov,
    jobs,
    legal,
    local,
    marketplace,
    mega_search,
    monitoring,
    news,
    prediction_markets,
    realestate,
    research,
    schema_extract,
    scraping,
    site_mapping,
    sports,
    sports_bankroll,
    sports_context,
    sports_derivatives,
    sports_futures,
    sports_live_intel,
    sports_player_intel,
    sports_sharp_intel,
    sportsbooks,
    travel,
    web_search,
)
from ._common import (
    _apply_offset,
    _call_domain_dispatcher,
    _callable_accepts,
    _data_module_unavailable,
    _domain_module_unavailable,
    _domain_tool_kwargs,
    _missing_arg,
    _new_domain_tool_kwargs,
)
from .actor import ACTOR_TOOL_NAMES, _actor_catalog_entries, _actor_tool_kwargs, call_actor_tool
from .annotations import _TOOL_ANNOTATIONS, _annotations_for
from .appstore import _APP_STORE_TOOL_FNS, call_app_store_tool
from .attention import call_attention_tool
from .bidding import _BIDDING_TOOL_FNS, call_bidding_tool
from .climate import _CLIMATE_TOOL_FNS, call_climate_tool
from .compliance import _COMPLIANCE_TOOL_FNS, call_compliance_tool
from .crypto import _crypto_module_unavailable, call_crypto_tool
from .data import (
    _ENERGY_TOOL_FNS,
    _EVENTS_TOOL_FNS,
    _FOOD_TOOL_FNS,
    _FREIGHT_TOOL_FNS,
    _SUPPLY_TOOL_FNS,
    _broad_domain_tool_kwargs,
    call_energy_tool,
    call_events_tool,
    call_food_tool,
    call_freight_tool,
    call_supply_tool,
)
from .deals import _DEALS_TOOL_FNS, call_deals_tool
from .gov import (
    _GOV_TOOL_FNS,
    _IP_TOOL_FNS,
    _call_candidate_domain_tool,
    call_gov_tool,
    call_ip_tool,
)
from .jobs import call_jobs_tool
from .legal import call_legal_tool
from .local import call_local_tool
from .marketplace import _marketplace_module_unavailable, call_marketplace_tool
from .news import _NEWS_TOOL_FNS, call_news_tool
from .realestate import call_realestate_tool
from .research import _RESEARCH_TOOL_FNS, call_research_tool
from .sports import (
    _SPORTS_TOOL_FNS,
    _sports_module_unavailable,
    _sports_tool_kwargs,
    call_sports_tool,
)
from .travel import call_travel_tool

__all__ = [
    "ACTOR_TOOL_NAMES",
    "PRY_TOOLS",
    "PRY_TOOL_NAMES",
    "_APP_STORE_TOOL_FNS",
    "_BIDDING_TOOL_FNS",
    "_CLIMATE_TOOL_FNS",
    "_COMPLIANCE_TOOL_FNS",
    "_DEALS_TOOL_FNS",
    "_ENERGY_TOOL_FNS",
    "_EVENTS_TOOL_FNS",
    "_FOOD_TOOL_FNS",
    "_FREIGHT_TOOL_FNS",
    "_GOV_TOOL_FNS",
    "_IP_TOOL_FNS",
    "_NEWS_TOOL_FNS",
    "_RESEARCH_TOOL_FNS",
    "_SPORTS_TOOL_FNS",
    "_SUPPLY_TOOL_FNS",
    "_TOOL_ANNOTATIONS",
    "_actor_catalog_entries",
    "_actor_tool_kwargs",
    "_annotations_for",
    "_apply_offset",
    "_broad_domain_tool_kwargs",
    "_call_candidate_domain_tool",
    "_call_domain_dispatcher",
    "_callable_accepts",
    "_crypto_module_unavailable",
    "_data_module_unavailable",
    "_domain_module_unavailable",
    "_domain_tool_kwargs",
    "_marketplace_module_unavailable",
    "_missing_arg",
    "_new_domain_tool_kwargs",
    "_sports_module_unavailable",
    "_sports_tool_kwargs",
    "call_actor_tool",
    "call_app_store_tool",
    "call_attention_tool",
    "call_bidding_tool",
    "call_climate_tool",
    "call_compliance_tool",
    "call_crypto_tool",
    "call_deals_tool",
    "call_energy_tool",
    "call_events_tool",
    "call_food_tool",
    "call_freight_tool",
    "call_gov_tool",
    "call_ip_tool",
    "call_jobs_tool",
    "call_legal_tool",
    "call_local_tool",
    "call_marketplace_tool",
    "call_news_tool",
    "call_realestate_tool",
    "call_research_tool",
    "call_sports_tool",
    "call_supply_tool",
    "call_travel_tool",
]

# Aggregate the per-domain tool lists into the single registry, preserving
# the exact tool order of the former monolithic PRY_TOOLS list.
PRY_TOOLS: list[dict[str, Any]] = [
    *scraping.PRY_TOOLS,
    *monitoring.PRY_TOOLS,
    *compliance.PRY_TOOLS,
    *scraping.PRY_EXTRACT_TOOLS,
    *billing.PRY_TOOLS,
    *crypto.PRY_TOOLS,
    *marketplace.PRY_TOOLS,
    *crypto.PRY_TOKEN_SECURITY_TOOLS,
    *legal.PRY_TOOLS,
    *realestate.PRY_TOOLS,
    *jobs.PRY_TOOLS,
    *travel.PRY_TOOLS,
    *attention.PRY_TOOLS,
    *local.PRY_TOOLS,
    *gov.PRY_TOOLS,
    *gov.PRY_IP_TOOLS,
    *sports.PRY_TOOLS,
    *sportsbooks.PRY_TOOLS,
    *prediction_markets.PRY_TOOLS,
    *sports_futures.PRY_TOOLS,
    *sports_derivatives.PRY_TOOLS,
    *sports_bankroll.PRY_TOOLS,
    *sports_player_intel.PRY_TOOLS,
    *sports_sharp_intel.PRY_TOOLS,
    *sports_live_intel.PRY_TOOLS,
    *sports_context.PRY_TOOLS,
    *site_mapping.PRY_TOOLS,
    *content_filter.PRY_FILTER_TOOLS,
    *web_search.PRY_SEARCH_TOOLS,
    *mega_search.PRY_MEGA_SEARCH_TOOLS,
    *actions.PRY_TOOLS,
    *schema_extract.PRY_SCHEMA_TOOLS,
    *adaptive.PRY_ADAPTIVE_TOOLS,
    *scraping.PRY_SOURCE_TOOLS,
    *climate.PRY_TOOLS,
    *research.PRY_TOOLS,
    *data.PRY_TOOLS,
    *appstore.PRY_TOOLS,
    *news.PRY_TOOLS,
    *compliance.PRY_WATCH_TOOLS,
    *deals.PRY_TOOLS,
    *bidding.PRY_TOOLS,
    *actor.PRY_TOOLS,
]

# 2026-09-01 audit: every Pry tool reaches the open web (target sites, public
# feeds, on-chain verifiers). The MCP spec defaults openWorldHint to true, but
# directories and agent clients rank explicit declarations higher — declare it
# on all 76 rather than relying on the default.
for _tool in PRY_TOOLS:
    _tool.setdefault("annotations", {**_annotations_for(str(_tool["name"])), "openWorldHint": True})

# Frozen set of every registered tool name — used by the registry-sync tests
# to assert server.json / glama.json / pulsemcp.json / llms.txt stay in sync.
PRY_TOOL_NAMES: frozenset[str] = frozenset(str(t["name"]) for t in PRY_TOOLS)


def _sync_actor_catalog_description() -> None:
    """Keep the pry_actor_catalog description's actor count honest.

    ALL_PRESETS grows over time; a hardcoded count in the static tool list
    drifts (it said 94 when the table reached 109). Patch the description
    with the live len(ALL_PRESETS) at import; on any import failure fall
    back to the neutral wording (no count).
    """
    try:
        from actor_factory.presets import ALL_PRESETS

        count = len(ALL_PRESETS)
    except ImportError:  # pragma: no cover - presets not installed yet
        count = None
    for tool in PRY_TOOLS:
        if tool.get("name") == "pry_actor_catalog":
            if count is not None:
                tool["description"] = tool["description"].replace("(94)", f"({count})")
            else:
                tool["description"] = tool["description"].replace(" (94)", "")
            break


_sync_actor_catalog_description()
