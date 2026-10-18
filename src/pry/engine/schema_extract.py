"""Pry — ScrapeGraphAI-style schema-based extraction engine.

Instead of writing CSS selectors, callers provide a JSON schema describing
WHAT data they want (``{"product_name": "the product title", "price": ...}``)
and the engine figures out WHERE it lives on the page:

1. Pattern extraction first (free, no LLM): JSON-LD, meta tags, and
   label/context heuristics.
2. AI fallback for any fields pattern extraction missed, using the existing
   :class:`pry.engine.extractor.SchemaExtractor` (Ollama).

All async functions never raise — they return ``{}`` (or an error-shaped
result) on failure.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from pry.core.errors import InvalidRequestError

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 20


def _validate_selector(selector: str, *, field: str) -> str:
    """Validate a user-supplied CSS selector (ReDoS guard) before cssselect.

    Raises ``InvalidRequestError`` so the API maps it to a 400 field error
    instead of leaking a parser exception or running a pathological selector.
    """
    try:
        from extraction.css import _validate_css_selector
    except ImportError:  # pragma: no cover - extraction ships with Pry
        return selector
    try:
        return _validate_css_selector(selector)
    except ValueError as exc:
        raise InvalidRequestError(f"Invalid {field}: {exc}", details={"field": field}) from exc


def _normalize_schema(schema: dict[str, Any] | None) -> dict[str, str]:
    """Normalize a user schema to ``{field_name: description}``.

    Accepts either the flat form ``{"price": "product price"}`` or the
    structured form ``{"fields": [{"name": "price", "description": ...}]}``.
    """
    if not isinstance(schema, dict):
        return {}
    fields = schema.get("fields")
    if isinstance(fields, list):
        out: dict[str, str] = {}
        for f in fields:
            if isinstance(f, dict) and f.get("name"):
                out[str(f["name"])] = str(f.get("description") or f["name"])
        return out
    return {str(k): str(v) for k, v in schema.items() if k != "fields"}


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


def _pattern_extract(html: str, content: str, schema: dict[str, str]) -> dict[str, Any]:
    """Free pattern extraction: JSON-LD, meta tags, then text heuristics."""
    data: dict[str, Any] = {}
    if not schema:
        return data

    # 1. JSON-LD structured data (most accurate source)
    if html:
        try:
            from pry.engine.schema_extraction import SchemaExtractor as JsonLdExtractor

            jsonld_items = JsonLdExtractor().extract_jsonld(html)
            for field in schema:
                if field in data:
                    continue
                for item in jsonld_items:
                    val = _jsonld_lookup(item, field)
                    if val is not None:
                        data[field] = val
                        break
        except Exception as exc:  # noqa: BLE001 — best-effort source
            logger.debug("schema_extract_jsonld_failed", extra={"error": str(exc)[:120]})

    # 2. Meta tags (description, og:*, twitter:*)
    if html:
        meta = _meta_tags(html)
        for field in schema:
            if field in data:
                continue
            for key in (field, f"og:{field}", f"twitter:{field}"):
                if key in meta:
                    data[field] = meta[key]
                    break

    # 3. Text heuristics via the existing pattern extractor
    missing = [f for f in schema if f not in data]
    if missing and content:
        try:
            from pry.engine.extractor import SchemaExtractor

            heur = SchemaExtractor()._pattern_extract(content, {f: schema[f] for f in missing})
            data.update(heur)
        except Exception as exc:  # noqa: BLE001 — best-effort source
            logger.debug("schema_extract_heuristic_failed", extra={"error": str(exc)[:120]})

    return data


def _jsonld_lookup(item: dict[str, Any], field: str) -> Any | None:
    """Look up a schema field inside one JSON-LD item (with common aliases)."""
    aliases = {
        "name": ("name", "headline", "title"),
        "title": ("name", "headline", "title"),
        "price": ("price", "lowPrice", "highPrice"),
        "description": ("description", "articleBody", "abstract"),
        "author": ("author", "creator", "byArtist"),
        "date": ("datePublished", "uploadDate", "startDate"),
        "image": ("image", "thumbnailUrl", "logo"),
        "url": ("url", "@id", "mainEntityOfPage"),
    }
    keys = aliases.get(field, (field,))
    for key in keys:
        val = item.get(key)
        if isinstance(val, dict):  # e.g. offers: {"price": 9.99}
            for sub in keys:
                if sub in val:
                    return val[sub]
            return None
        if isinstance(val, list):
            val = val[0] if val else None
            if isinstance(val, dict):
                continue
        if val not in (None, "", []):
            return val
    return None


def _meta_tags(html: str) -> dict[str, str]:
    """Extract <meta name/content> and <meta property/content> pairs."""
    meta: dict[str, str] = {}
    for m in re.finditer(
        r"<meta\s+[^>]*?(?:name|property)=['\"]([^'\"]+)['\"][^>]*?content=['\"]([^'\"]*)['\"]",
        html,
        re.IGNORECASE,
    ):
        key, val = m.group(1).lower(), m.group(2).strip()
        if val and key not in meta:
            meta[key] = val
    return meta


def _confidence(data: dict[str, Any], schema: dict[str, str], method: str) -> float:
    """Simple confidence score: fraction of schema fields filled, weighted by source."""
    if not schema:
        return 0.0
    filled = sum(1 for f in schema if data.get(f) not in (None, "", [], {}))
    base = filled / len(schema)
    if method == "pattern":
        return round(min(base, 1.0), 2)
    if method == "ai":
        return round(min(base * 0.85, 1.0), 2)  # LLM output slightly less trusted
    return round(min(base, 1.0), 2)  # hybrid: pattern-anchored


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
        try:
            from pry.engine.extractor import SchemaExtractor

            ai_result = await SchemaExtractor().extract(
                page["content"], {f: norm[f] for f in missing}, mode="llm"
            )
            ai_result.pop("_error", None)
            ai_result.pop("_raw", None)
            fresh = {k: v for k, v in ai_result.items() if v not in (None, "")}
            if fresh:
                data.update(fresh)
                method = "hybrid" if method == "pattern" else "ai"
        except Exception as exc:  # noqa: BLE001 — contract: never raise
            logger.warning("schema_extract_ai_failed", extra={"error": str(exc)[:120]})

    return {
        "url": url,
        "data": data,
        "method": method,
        "confidence": _confidence(data, norm, method),
    }


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


def infer_schema_from_example(example: dict) -> dict:
    """Generate a JSON schema from an example data dict.

    Given ``{"product_name": "Widget", "price": 9.99}``, returns a schema
    describing the expected output format — useful for users who don't want
    to write schemas manually. Never raises.
    """
    if not isinstance(example, dict):
        return {}
    fields: list[dict[str, str]] = []
    for key, val in example.items():
        if isinstance(val, bool):
            ftype = "boolean"
        elif isinstance(val, (int, float)):
            ftype = "number"
        elif isinstance(val, list):
            ftype = "array"
        elif isinstance(val, dict):
            ftype = "object"
        else:
            ftype = "string"
        fields.append(
            {"name": str(key), "type": ftype, "description": f"the {str(key).replace('_', ' ')}"}
        )
    return {
        "type": "object",
        "properties": {f["name"]: {"type": f["type"]} for f in fields},
        "fields": fields,
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
    html = page["html"]
    if not html:
        return []
    try:
        from lxml import html as lxml_html

        tree = lxml_html.fromstring(html)
        tables = (
            tree.cssselect(table_selector) if table_selector != "table" else tree.xpath("//table")
        )
        if not tables:
            return []
        table = tables[0]
        rows = table.xpath(".//tr")
        if not rows:
            return []
        header_cells = rows[0].xpath("./th|./td")
        headers = [c.text_content().strip() or f"col_{i}" for i, c in enumerate(header_cells)]
        out: list[dict[str, str]] = []
        for row in rows[1:]:
            cells = row.xpath("./td|./th")
            if not cells:
                continue
            values = [c.text_content().strip() for c in cells]
            out.append(
                {headers[i] if i < len(headers) else f"col_{i}": v for i, v in enumerate(values)}
            )
        return out
    except Exception as exc:  # noqa: BLE001 — contract: never raise
        logger.warning("extract_table_failed", extra={"url": url, "error": str(exc)[:120]})
        return []
