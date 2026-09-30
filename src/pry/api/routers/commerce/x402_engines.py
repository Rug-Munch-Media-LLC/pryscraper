"""x402 catalog engine→MCP-tool mapping.

Split out of ``x402.py`` so the catalog's engine registry has one owner. The
router module re-exports ``ENGINE_TOOLS`` and reads it through this module
attribute at call time, so patching either module is honoured.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

# Engine -> MCP tool binding for the x402 catalog: every actor processor
# maps to the MCP tool exposing the same capability. Actors with
# processor=None run the raw scrape/crawl/screenshot engines directly.
ENGINE_TOOLS: dict[str | None, str] = {
    None: "pry_scrape",
    "scrape": "pry_scrape",
    "crawl": "pry_crawl",
    "extract": "pry_extract",
    "monitor": "pry_monitor",
    "news": "pry_news",
    "jsondata": "pry_all_sources",
    "leads": "pry_places_search",
    "price": "pry_flights_grid",
    "audit": "pry_domain",
    "seo": "pry_trends",
    "tech": "pry_enrich",
    "invoice": "pry_parse_document",
    "corpus": "pry_crawl",
    "backlinks": "pry_domain",
}


def catalog_data(
    x402_pricing: dict,
    paid_endpoints: dict,
    actors: list | None,
    settlement: dict,
) -> dict:
    """The catalog's ``data`` payload, shared by the available/unavailable paths.

    ``actors=None`` marks the actor section unavailable, which is deliberately
    distinct from an empty list: a factory that genuinely ships no presets is
    indistinguishable from a broken one, and reporting [] would tell a client
    pricing a call that a real capability does not exist.
    """
    return {
        "operations": {
            op: {"price_usd": tier.get("price_usd"), "description": tier.get("description")}
            for op, tier in sorted(x402_pricing.items())
        },
        "paid_endpoints": dict(sorted(paid_endpoints.items())),
        "engines": {str(k): v for k, v in ENGINE_TOOLS.items()},
        "actors": actors,
        "actor_count": None if actors is None else len(actors),
        "settlement": settlement,
    }
