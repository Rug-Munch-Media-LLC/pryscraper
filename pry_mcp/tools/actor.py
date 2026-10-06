"""Pry - MCP tool definitions: Apify-parity actor tools and the ``call_actor_tool`` dispatcher..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import logging
from typing import Any

from ._common import _missing_arg

logger = logging.getLogger(__name__)

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_actor_catalog",
        "description": (
            "List every Pry Apify Store actor (94) with description, category, pricing "
            "events and per-event USD price. Store parity surface: anything "
            "runnable on Apify is discoverable here. Filter by optional "
            "'domain' substring (e.g. 'monitor', 'crypto', 'seo'). Supports "
            "offset/limit pagination over the full catalog."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional case-insensitive substring filter over actor name/title.",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Number of actors to skip before the page (pagination)",
                },
                "limit": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "description": "Maximum actors per page (0 = all)",
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "total": {"type": "integer"},
                "count": {"type": "integer", "description": "Actors on this page"},
                "actors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "actor": {"type": "string"},
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "category": {"type": "string"},
                            "icon": {"type": "string"},
                            "icon_hd": {"type": "string"},
                            "processor": {"type": ["string", "null"]},
                            "uses_browser": {"type": "boolean"},
                            "min_memory_mbytes": {"type": "integer"},
                            "pricing_events": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "event": {"type": "string"},
                                        "title": {"type": "string"},
                                        "price_usd": {"type": "number"},
                                    },
                                    "required": ["event", "price_usd"],
                                },
                            },
                        },
                        "required": ["actor", "title", "category", "pricing_events"],
                    },
                },
            },
            "required": ["success", "total", "actors"],
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "pry_actor_run",
        "description": (
            "Run any Pry Apify actor's pipeline locally over URLs - same "
            "PPEScraperRunner + processor code path as the deployed store "
            "actors. Use after pry_actor_catalog: pass the actor name plus "
            "target urls; results are the same dataset items the Apify run "
            "would produce. x402 pay-per-call: each processed URL bills the "
            "actor's first PPE pricing event (see pry_actor_catalog / "
            "pry_x402_pricing for per-event USD prices). Examples: actor='news-feed-monitor', "
            "actor='universal-scraper', actor='token-safety-scanner'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "actor": {
                    "type": "string",
                    "description": "Actor name without the pry- prefix, e.g. 'news-feed-monitor'.",
                },
                "urls": {
                    "type": "array",
                    "items": {"type": "string", "format": "uri"},
                    "description": "Target URLs for the actor pipeline.",
                },
                "max_items": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 25,
                    "description": "Hard cap on processed URLs (runaway protection).",
                },
            },
            "required": ["actor", "urls"],
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "actor": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "status": {"type": "string"},
                            "method": {"type": "string"},
                            "content": {"type": "string"},
                            "scraped_at": {"type": "string"},
                            "error": {"type": "string"},
                        },
                    },
                    "description": "Dataset items, same shape as the Apify actor run",
                },
                "item_count": {"type": "integer"},
                "format": {
                    "type": "string",
                    "description": "Output format used for item content (default: markdown)",
                },
                "equivalent_apify_charge_usd": {
                    "type": "number",
                    "description": "PPE charge the equivalent Apify run would bill",
                },
                "note": {"type": "string"},
            },
            "required": ["success", "actor", "items", "item_count"],
        },
    },
]

# ── Apify actor parity layer ─────────────────────────────────────────────────
#
# Store parity: every Pry Apify Actor is reachable from MCP. Instead of one
# near-duplicate tool definitions (tool-list bloat breaks MCP clients), the
# surface is catalog-driven: ``pry_actor_catalog`` discovers, ``pry_actor_run``
# executes through the SAME PPEScraperRunner.process_url + PROCESSORS code
# path the deployed actors use on the platform.


def _actor_catalog_entries() -> list[dict[str, Any]]:
    """Catalog rows for every preset, sorted by name for determinism."""
    from actor_factory.metadata import PRESET_CATEGORY_MAP
    from actor_factory.presets import ALL_PRESETS

    entries: list[dict[str, Any]] = []
    for name in sorted(ALL_PRESETS):
        spec = ALL_PRESETS[name]
        entries.append(
            {
                "actor": spec.name.removeprefix("pry-"),
                "title": spec.title,
                "description": spec.description,
                "category": PRESET_CATEGORY_MAP.get(spec.name, "OTHER"),
                "icon": spec.icon,
                "icon_hd": spec.icon_hd,
                "processor": spec.processor,
                "uses_browser": spec.uses_browser,
                "min_memory_mbytes": spec.min_memory_mbytes,
                "pricing_events": [
                    {
                        "event": e.name,
                        "title": e.title,
                        "price_usd": e.price_usd,
                    }
                    for e in spec.pricing_events
                ],
            }
        )
    return entries


def _actor_tool_kwargs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Options dict passed through to the actor pipeline (everything except
    the runner's own control keys)."""
    return {k: v for k, v in arguments.items() if k not in ("actor", "urls", "max_items")}


async def call_actor_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch the Apify-parity tools (catalog + run). Returns None for
    non-actor tools so callers fall through to other dispatchers."""
    if name == "pry_actor_catalog":
        domain = arguments.get("domain")
        entries = _actor_catalog_entries()
        if domain:
            needle = str(domain).lower()
            entries = [e for e in entries if needle in e["actor"] or needle in e["title"].lower()]
        # offset/limit pagination over the (109+) row catalog.
        try:
            offset = int(arguments.get("offset") or 0)
        except (TypeError, ValueError) as e:
            logger.warning(
                "suppressed %s in call_actor_tool (actor.py:236): %s",
                "(TypeError, ValueError)",
                e,
            )
            offset = 0
        limit = arguments.get("limit")
        total = len(entries)
        if offset > 0:
            entries = entries[offset:]
        if isinstance(limit, int) and limit > 0:
            entries = entries[:limit]
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": True,
                            "total": total,
                            "count": len(entries),
                            "actors": entries,
                        },
                        indent=2,
                    ),
                }
            ]
        }

    if name == "pry_actor_run":
        from actor_factory.presets import ALL_PRESETS
        from actor_factory.processors import PROCESSORS
        from actor_factory.runner import ActorRunConfig, PPEScraperRunner

        actor = arguments.get("actor")
        urls = arguments.get("urls") or []
        if not actor or not isinstance(actor, str):
            return _missing_arg(name, "actor")
        spec = ALL_PRESETS.get(f"pry-{actor}")
        if spec is None:
            known = ", ".join(sorted(a.removeprefix("pry-") for a in ALL_PRESETS))
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "error": f"unknown actor '{actor}'. Known actors: {known}",
                                "code": "UNKNOWN_ACTOR",
                            }
                        ),
                    }
                ],
                "isError": True,
            }
        if not urls:
            return _missing_arg(name, "urls")

        max_items = arguments.get("max_items")
        if not isinstance(max_items, int) or max_items < 1:
            max_items = 25
        options = _actor_tool_kwargs(arguments)
        options.setdefault("output_format", "markdown")

        config = ActorRunConfig(
            primary_event=spec.pricing_events[0].name if spec.pricing_events else "item",
            processor_name=spec.processor,
        )
        runner = PPEScraperRunner(config)
        processor = PROCESSORS.get(spec.processor) if spec.processor else None

        items: list[dict[str, Any]] = []
        state: dict[str, Any] = {}
        for url in list(urls)[:max_items]:
            try:
                item = await runner.process_url(url, options)
            except Exception as e:  # noqa: BLE001 - bad targets must not kill batches
                logger.warning(
                    "suppressed %s in call_actor_tool (actor.py:308): %s",
                    "Exception",
                    e,
                )
                item = {
                    "url": url,
                    "status": "error",
                    "error": f"processing_failed: {str(e)[:120]}",
                }
            if processor is not None:
                item = processor(url, item, options, state)
            items.append(item)

        charged = spec.pricing_events[0].price_usd * len(items) if spec.pricing_events else 0.0
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": True,
                            "actor": spec.name.removeprefix("pry-"),
                            "items": items,
                            "item_count": len(items),
                            "format": options.get("output_format", "markdown"),
                            "equivalent_apify_charge_usd": round(charged, 6),
                            "note": (
                                "Ran locally via MCP - same pipeline as the Apify "
                                "actor; on-platform runs bill the equivalent PPE event."
                            ),
                        },
                        indent=2,
                        default=str,
                    ),
                }
            ]
        }

    return None


ACTOR_TOOL_NAMES: frozenset[str] = frozenset({"pry_actor_catalog", "pry_actor_run"})
