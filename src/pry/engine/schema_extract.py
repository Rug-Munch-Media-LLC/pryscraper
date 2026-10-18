"""Pry — ScrapeGraphAI-style schema-based extraction engine.

Instead of writing CSS selectors, callers provide a JSON schema describing
WHAT data they want (``{"product_name": "the product title", "price": ...}``)
and the engine figures out WHERE it lives on the page:

1. Pattern extraction first (free, no LLM): JSON-LD, meta tags, and
   label/context heuristics.
2. AI fallback for any fields pattern extraction missed, using the existing
   :class:`pry.engine.extractor.SchemaExtractor` (Ollama).

Helpers live in :mod:`~pry.engine.schema_fields`,
:mod:`~pry.engine.schema_patterns` and :mod:`~pry.engine.schema_table`.
All async functions never raise — they return ``{}`` (or an error-shaped
result) on failure.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pry.engine.schema_fields import (
    confidence as _confidence,
    infer_schema_from_example,
    normalize_schema as _normalize_schema,
)
from pry.engine.schema_patterns import (
    jsonld_lookup as _jsonld_lookup,
    meta_tags as _meta_tags,
    pattern_extract as _pattern_extract,
)
from pry.engine.schema_table import parse_table
from pry.engine.selector_validate import _validate_selector

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 20


async def _fetch_page(url: str) -> dict[str, Any]:
    """Fetch a page via the 15-tier UltimateScraper fallback chain.

    Returns ``{"html": str, "content": str, "method": str}`` — empty strings
    on failure. Never raises.
    """
    try:
        from pry.engine.ultimate_scraper import UltimateScraper

        result = await UltimateScraper().scrape(url)
        if not isinstance(result, dict) or result.get("status") not in ("ok", "success"):
            return {"html": "", "content": "", "method": ""}
        return {
            "html": str(result.get("raw_html") or ""),
            "content": str(result.get("content") or ""),
            "method": str(result.get("method") or ""),
        }
    except Exception as exc:  # noqa: BLE001 — contract: never raise
        logger.warning("schema_extract_fetch_failed", extra={"url": url, "error": str(exc)[:120]})
        return {"html": "", "content": "", "method": ""}


async def extract_by_schema(url: str, schema: dict, use_ai: bool = True) -> dict:
    """Extract data matching ``schema`` from ``url``.

    Schema: ``{"field_name": "description of what to extract"}`` or
    ``{"fields": [{"name": ..., "description": ...}]}``.

    Pattern extraction (JSON-LD / meta tags / heuristics) is tried first;
    any missing fields fall back to AI extraction via the existing
    :class:`pry.engine.extractor.SchemaExtractor` when ``use_ai`` is true.

    Returns ``{"url", "data", "method", "confidence"}`` — ``{}`` on failure.
    Never raises.
    """
    if not url or not isinstance(schema, dict):
        return {}
    norm = _normalize_schema(schema)
    if not norm:
        return {}

    page = await _fetch_page(url)
    if not page["html"] and not page["content"]:
        return {"url": url, "data": {}, "method": "none", "confidence": 0.0}

    data = _pattern_extract(page["html"], page["content"], norm)
    method = "pattern" if data else "none"

    missing = [f for f in norm if data.get(f) in (None, "", [], {})]
    if missing and use_ai and page["content"]:
        data, method = await _ai_fill(page["content"], norm, data, method, missing)

    return {
        "url": url,
        "data": data,
        "method": method,
        "confidence": _confidence(data, norm, method),
    }


async def _ai_fill(
    content: str,
    norm: dict[str, str],
    data: dict[str, Any],
    method: str,
    missing: list[str],
) -> tuple[dict[str, Any], str]:
    """Fill missing fields from the LLM; never raises, returns (data, method)."""
    try:
        from pry.engine.extractor import SchemaExtractor

        ai_result = await SchemaExtractor().extract(
            content, {f: norm[f] for f in missing}, mode="llm"
        )
        ai_result.pop("_error", None)
        ai_result.pop("_raw", None)
        fresh = {k: v for k, v in ai_result.items() if v not in (None, "")}
        if fresh:
            data.update(fresh)
            method = "hybrid" if method == "pattern" else "ai"
    except Exception as exc:  # noqa: BLE001 — contract: never raise
        logger.warning("schema_extract_ai_failed", extra={"error": str(exc)[:120]})
    return data, method


async def extract_batch_by_schema(
    urls: list[str], schema: dict, max_concurrent: int = 5
) -> list[dict]:
    """Extract from multiple URLs with the same schema, bounded concurrency.

    Returns one result dict per URL (same shape as :func:`extract_by_schema`),
    in input order. Never raises.
    """
    if not isinstance(urls, list) or not isinstance(schema, dict):
        return []
    sem = asyncio.Semaphore(max(1, min(max_concurrent, _MAX_CONCURRENT)))

    async def _one(u: str) -> dict:
        async with sem:
            return await extract_by_schema(u, schema)

    return list(await asyncio.gather(*(_one(u) for u in urls)))


async def extract_with_prompt(url: str, prompt: str, schema: dict | None = None) -> dict:
    """Natural-language extraction: describe what you want, get structured data.

    Example prompt: ``"Extract the product name, price, and all reviews"``.
    The prompt is combined with the optional ``schema`` and sent to the LLM
    extraction path in :class:`pry.engine.extractor.SchemaExtractor`.

    Returns ``{"url", "data", "method", "confidence"}`` — ``{}`` on failure.
    Never raises.
    """
    if not url or not prompt:
        return {}
    norm = _normalize_schema(schema)
    page = await _fetch_page(url)
    content = page["content"] or page["html"][:20000]
    if not content:
        return {"url": url, "data": {}, "method": "none", "confidence": 0.0}

    data: dict[str, Any] = {}
    method = "none"
    try:
        from pry.engine.extractor import SchemaExtractor

        llm_schema: dict[str, str] = dict(norm)
        llm_schema["_instruction"] = prompt
        result = await SchemaExtractor().extract(content, llm_schema, mode="llm")
        result.pop("_error", None)
        result.pop("_raw", None)
        data = {k: v for k, v in result.items() if k != "_instruction" and v not in (None, "")}
        if data:
            method = "ai"
    except Exception as exc:  # noqa: BLE001 — contract: never raise
        logger.warning("extract_with_prompt_failed", extra={"error": str(exc)[:120]})

    return {
        "url": url,
        "data": data,
        "method": method,
        "confidence": _confidence(data, norm, method),
    }


async def extract_table(url: str, table_selector: str = "table") -> list[dict]:
    """Extract an HTML table as a list of dicts (header → value per row).

    Returns ``[]`` on failure. Raises :class:`InvalidRequestError` (HTTP 400)
    when the caller-supplied selector is unsafe — a hostile selector is a
    request error, not an extraction failure, and must never reach cssselect.
    """
    if not url:
        return []
    _validate_selector(table_selector, field="table_selector")
    page = await _fetch_page(url)
    if not page["html"]:
        return []
    try:
        return parse_table(page["html"], table_selector)
    except Exception as exc:  # noqa: BLE001 — contract: never raise
        logger.warning("extract_table_failed", extra={"url": url, "error": str(exc)[:120]})
        return []


__all__ = [
    "extract_batch_by_schema",
    "extract_by_schema",
    "extract_table",
    "extract_with_prompt",
    "infer_schema_from_example",
]
