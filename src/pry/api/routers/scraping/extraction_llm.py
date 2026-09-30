# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""LLM + chunking extraction implementation layer.

Extracted from ``extraction`` (thin entrypoint re-exports ``extract_llm``)
so the router file holds route wiring only.

``extraction`` owns the shared ``scraper``/``logger`` names. They are read
back through the entrypoint at CALL time rather than bound locally, so a test
patching ``extraction.scraper`` keeps working — module-attribute
monkeypatching stays effective instead of being frozen into a local at import
time. No back-reference is wired up by the entrypoint, so this module also
imports cleanly on its own.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from fastapi import Body

from pry.core.errors import ScrapeError
from pry.engine.extraction import extract_with_chunking

if TYPE_CHECKING:
    from types import ModuleType


def _owner() -> ModuleType:
    """Return the thin entrypoint that owns the shared router names.

    Resolved at call time so this layer never binds a local copy of ``scraper``
    at import time — patching the entrypoint stays effective.
    """
    return import_module(f"{__name__.rsplit('.', 1)[0]}.extraction")


async def extract_llm(
    url: str = Body(...),
    instruction: str = Body("Extract all key information from this content."),
    schema: dict[str, Any] | None = Body(None),
    chunk_strategy: str = Body("topic"),
    query: str = Body(""),
    top_k: int = Body(5),
) -> dict[str, Any]:
    """Extract structured data using LLM with intelligent chunking.

    Chunks content by strategy (topic/sentence/regex), optionally filters
    by relevance to query, then extracts from each chunk.
    """
    result = await _owner().scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Scrape failed")

    content = result.get("content", "")
    if not content:
        raise ScrapeError("No content returned from scraper")

    chunks = await extract_with_chunking(
        content=content,
        instruction=instruction,
        schema=schema,
        chunk_strategy=chunk_strategy,
        query=query,
        top_k=top_k,
    )

    return {
        "success": True,
        "data": {
            "chunks": chunks,
            "total_chunks": len(chunks),
            "strategy": chunk_strategy,
        },
    }
