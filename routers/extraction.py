"""Pry — Extraction router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Body

from pry.api.client import get_client
from pry.core.deps import advanced, scraper
from pry.core.errors import InvalidRequestError, ScrapeError
from pry.engine.extraction import JsonCssExtractionStrategy, extract_with_chunking
from pry.engine.extractor import SchemaExtractor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Extraction"])


@router.post(
    "/v1/extract-table", tags=["Extraction"], summary="Extract HTML tables as structured data"
)
async def extract_table(url: str = Body(...), table_index: int = 0) -> dict[str, Any]:
    """Extract HTML tables from a page as structured data.
    Firecrawl doesn't support table extraction at all."""
    import pandas as pd

    client = await get_client()
    resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
    tables = pd.read_html(resp.text)
    if table_index >= len(tables):
        raise InvalidRequestError(f"Only {len(tables)} tables found")
    df = tables[table_index]
    return {
        "success": True,
        "data": {
            "table_index": table_index,
            "total_tables": len(tables),
            "columns": list(df.columns),
            "rows": df.to_dict(orient="records"),
            "html": df.to_html(index=False),
        },
    }


@router.post("/v1/links", tags=["Extraction"], summary="Analyze links on a page")
async def analyze_links(url: str = Body(...)) -> dict[str, Any]:
    """Analyze all links on a page — internal, external, broken, social.
    Firecrawl only has basic map functionality."""
    html = ""
    try:
        client = await get_client()
        resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
        html = resp.text
    except httpx.HTTPError:
        logger.warning("links_fetch_failed", extra={"url": url})
    base = urlparse(url).netloc
    internal, external = set(), set()
    for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', html):
        link = m.group(1)
        if urlparse(link).netloc == base:
            internal.add(link.split("#")[0])
        else:
            external.add(link.split("#")[0])
    for m in re.finditer(r'href=["\'](/[^"\']+)["\']', html):
        internal.add(urljoin(url, m.group(1)).split("#")[0])
    social = advanced.find_social_links(html)
    return {
        "success": True,
        "data": {
            "url": url,
            "internal_count": len(internal),
            "external_count": len(external),
            "internal": sorted(internal)[:50],
            "external": sorted(external)[:50],
            "social": social,
        },
    }


@router.post("/v1/seo", tags=["Extraction"], summary="SEO analysis of a page")
async def analyze_seo(url: str = Body(...)) -> dict[str, Any]:
    """SEO analysis of a page: title, description, headings, images, keywords, readability.
    Firecrawl has zero SEO features."""
    client = await get_client()
    resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
    html = resp.text
    result = await scraper.scrape(url)
    content = result.get("content", "")

    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    desc = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html, re.I)
    h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    h2 = re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.I | re.S)
    imgs = re.findall(r"<img\s[^>]*\salt=[\"\']([^\"\']*)[\"\'][^>]*>", html, re.I)
    total_imgs = len(re.findall(r"<img\s", html, re.I))
    imgs_no_alt = total_imgs - len(imgs)

    return {
        "success": True,
        "data": {
            "url": url,
            "title": title.group(1).strip() if title else "",
            "title_length": len(title.group(1).strip()) if title else 0,
            "meta_description": desc.group(1).strip() if desc else "",
            "headings": {"h1": [h.strip() for h in h1], "h2": [h.strip() for h in h2]},
            "images_with_alt": len([a for a in imgs if a.strip()]),
            "images_without_alt": imgs_no_alt,
            "word_count": len(content.split()),
            "readability": advanced.readability(content),
            "keywords": advanced.keyword_density(content, 15),
        },
    }


@router.post(
    "/v1/schema", tags=["Extraction"], summary="Extract Schema.org/JSON-LD structured data"
)
async def extract_schema(url: str = Body(...)) -> dict[str, Any]:
    """Extract Schema.org/JSON-LD structured data from a page."""
    client = await get_client()
    resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
    html = resp.text
    schemas = advanced.extract_schema(html)
    return {"success": True, "data": {"url": url, "schemas": schemas}}


@router.post("/v1/emails", tags=["Extraction"], summary="Find email addresses on a page")
async def find_emails(url: str = Body(...)) -> dict[str, Any]:
    """Find all email addresses on a page."""
    try:
        client = await get_client()
        resp = await client.get(url, headers={"User-Agent": "Pry/3.0"}, timeout=15)
        html_text = resp.text
    except (httpx.HTTPError, httpx.RequestError):
        html_text = ""

    result = await scraper.scrape(url)
    emails = advanced.find_emails(result.get("content", ""))
    social = advanced.find_social_links(html_text)
    return {"success": True, "data": {"url": url, "emails": emails, "social": social}}


@router.post("/v1/extract", tags=["Extraction"], summary="Extract structured fields from a URL")
async def extract_stable(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = data.get("url", "")
    fields = data.get("fields", {})
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Extraction failed")

    ex = SchemaExtractor()
    extracted = await ex.extract(result.get("content", ""), fields, mode="llm")
    return {"success": True, "data": {"url": url, "fields": extracted}}


@router.post(
    "/v1/extract/css",
    tags=["Extraction"],
    summary="Extract structured data with CSS selectors (no LLM)",
)
async def extract_css(
    url: str = Body(...),
    schema: dict[str, Any] = Body(...),
    bypass_cloudflare: bool = Body(True),
) -> dict[str, Any]:
    """Extract structured JSON from a URL using CSS selector schema.

    Schema format:
    {
        "name": "products",
        "base_selector": ".product-card",
        "fields": [
            {"name": "title", "selector": "h3", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text", "transform": "float"},
            {"name": "link", "selector": "a", "type": "attribute", "attribute": "href"},
            {"name": "in_stock", "selector": ".stock", "type": "exists"},
        ]
    }
    """
    result = await scraper.scrape(url, {"bypass_cloudflare": bypass_cloudflare})
    html = result.get("raw_html", "")

    if not html:
        client = await get_client()
        resp = await client.get(
            url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
        )
        html = resp.text

    if not html:
        raise ScrapeError("No HTML content returned from scraper")

    strategy = JsonCssExtractionStrategy(schema)
    data = strategy.extract(html)

    return {
        "success": True,
        "data": {
            "schema": schema.get("name", "extracted"),
            "count": len(data),
            "items": data,
        },
    }


@router.post(
    "/v1/extract/llm", tags=["Extraction"], summary="Extract with LLM + chunking strategies"
)
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

    result = await scraper.scrape(url, {"bypass_cloudflare": True})
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


logger = logging.getLogger(__name__)
