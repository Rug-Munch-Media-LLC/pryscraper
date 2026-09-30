"""Pry — Extraction router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import io
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Body

from extraction.css import _validate_css_selector
from pry.api.client import get_client
from pry.api.routers.scraping.extraction_llm import extract_llm as extract_llm
from pry.api.routers.scraping.fetch import BROWSER_USER_AGENT, guard_get
from pry.core.deps import advanced, scraper
from pry.core.errors import InvalidRequestError, PryError, ScrapeError
from pry.engine.extraction import JsonCssExtractionStrategy
from pry.engine.extractor import SchemaExtractor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Extraction"])

# Re-register the moved route on THIS router. Decorating the imported symbol
# directly (rather than wrapping it) keeps `extract_llm is
# extraction_llm.extract_llm` true, so there is no second implementation to
# drift from the one the router dispatches.
router.post(
    "/v1/extract/llm", tags=["Extraction"], summary="Extract with LLM + chunking strategies"
)(extract_llm)

__all__ = [
    "analyze_links",
    "analyze_seo",
    "extract_css",
    "extract_llm",
    "extract_schema",
    "extract_stable",
    "extract_table",
    "extract_thumbnail",
    "find_emails",
    "router",
]


@router.post(
    "/v1/extract-table", tags=["Extraction"], summary="Extract HTML tables as structured data"
)
async def extract_table(url: str = Body(...), table_index: int = 0) -> dict[str, Any]:
    """Extract HTML tables from a page as structured data.
    Firecrawl doesn't support table extraction at all."""
    import pandas as pd

    client = await get_client()
    resp = await guard_get(client, url)
    # read_html's first arg is a FilePath | ReadBuffer[str]: a bare ``str`` is
    # read as a *filename* and raises FileNotFoundError, so the response body
    # must be wrapped in a StringIO buffer.
    tables = pd.read_html(io.StringIO(resp.text))
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
        resp = await guard_get(client, url)
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


@router.post("/v1/thumbnail", tags=["Extraction"], summary="Extract og:image/thumbnail from a URL")
async def extract_thumbnail(url: str = Body(...)) -> dict[str, Any]:
    """Extract the og:image, twitter:image, or first img src from a page.
    Uses Cloudflare bypass when needed. Returns the thumbnail URL or None."""
    try:
        result = await scraper.scrape(url, {"bypass_cloudflare": True})
        html = result.get("raw_html", "")
        if not html:
            client = await get_client()
            resp = await guard_get(client, url)
            html = resp.text
    except Exception:  # noqa: BLE001 — thumbnail is best-effort; any failure yields None
        # ``{"thumbnail": None}`` is the SAME payload a page with no og:image /
        # twitter:image / img tag returns, so a transport or parse failure would
        # be reported as "this page has no thumbnail" — a fabricated result.
        # Signal the failure explicitly instead.
        return {
            "success": False,
            "error": "thumbnail extraction failed",
            "data": {"thumbnail": None},
        }

    import re

    # Try og:image first
    og = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html, re.I)
    if og:
        return {"success": True, "data": {"thumbnail": og.group(1), "source": "og:image"}}

    # Try twitter:image
    tw = re.search(r'<meta\s+name="twitter:image"\s+content="([^"]+)"', html, re.I)
    if tw:
        return {"success": True, "data": {"thumbnail": tw.group(1), "source": "twitter:image"}}

    # Try twitter:image:src
    tws = re.search(r'<meta\s+name="twitter:image:src"\s+content="([^"]+)"', html, re.I)
    if tws:
        return {"success": True, "data": {"thumbnail": tws.group(1), "source": "twitter:image:src"}}

    # Try first img tag
    img = re.search(r'<img\s[^>]*src="([^"]+)"', html, re.I)
    if img:
        src = img.group(1)
        if src.startswith("/"):
            from urllib.parse import urljoin

            src = urljoin(url, src)
        return {"success": True, "data": {"thumbnail": src, "source": "first-img"}}

    return {"success": True, "data": {"thumbnail": None}}


@router.post("/v1/seo", tags=["Extraction"], summary="SEO analysis of a page")
async def analyze_seo(url: str = Body(...)) -> dict[str, Any]:
    """SEO analysis of a page: title, description, headings, images, keywords, readability.
    Firecrawl has zero SEO features."""
    client = await get_client()
    resp = await guard_get(client, url)
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
    resp = await guard_get(client, url)
    html = resp.text
    schemas = advanced.extract_schema(html)
    return {"success": True, "data": {"url": url, "schemas": schemas}}


@router.post("/v1/emails", tags=["Extraction"], summary="Find email addresses on a page")
async def find_emails(url: str = Body(...)) -> dict[str, Any]:
    """Find all email addresses on a page.

    ``emails`` come from the multi-tier scraper. ``social`` comes from a direct
    fetch of the page HTML, which can fail independently — when it does,
    ``social`` is empty and ``social_error`` names the failure so an empty list
    is never mistaken for "the page has no social links".
    """
    html_text = ""
    social_error: str | None = None
    try:
        client = await get_client()
        resp = await guard_get(client, url)
        html_text = resp.text
    except (httpx.HTTPError, httpx.RequestError, PryError) as e:
        # PryError covers the SSRF guard: it raises InvalidRequestError, which is
        # not an httpx error, so letting it escape would turn a rejected URL into
        # a 500. A blocked fetch belongs in the same channel as a failed one.
        social_error = f"{type(e).__name__}: {e}"[:300]
        logger.warning("emails_social_fetch_failed", extra={"url": url, "error": social_error})

    result = await scraper.scrape(url)
    emails = advanced.find_emails(result.get("content", ""))
    social = advanced.find_social_links(html_text)
    return {
        "success": True,
        "data": {
            "url": url,
            "emails": emails,
            "social": social,
            "social_error": social_error,
        },
    }


@router.post("/v1/extract", tags=["Extraction"], summary="Extract structured fields from a URL")
async def extract_stable(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Extract structured fields from a URL using an LLM.

    Scrapes the target URL (with Cloudflare bypass) and extracts the requested
    fields into a structured JSON object.

    **Request body**

    ```json
    {
      "url": "https://example.com/products",
      "fields": {
        "product_name": "The name of the product",
        "price": "The price in USD",
        "in_stock": "Whether the product is in stock"
      }
    }
    ```

    **Response**

    ```json
    {
      "success": true,
      "data": {
        "url": "https://example.com/products",
        "fields": {
          "product_name": "Acme Widget",
          "price": "$19.99",
          "in_stock": true
        }
      }
    }
    ```

    **x402 payment**: this endpoint is free and always public. For LLM-heavy
    extraction at scale, paid operations are gated behind x402 micropayments —
    see `GET /v1/x402/pricing`.
    """
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
        resp = await guard_get(client, url, timeout=30, user_agent=BROWSER_USER_AGENT)
        html = resp.text

    if not html:
        raise ScrapeError("No HTML content returned from scraper")

    # ReDoS guard: validate every user-supplied CSS selector in the schema
    # before it reaches the cssselect engine.
    base_selector = schema.get("base_selector")
    if base_selector:
        try:
            _validate_css_selector(base_selector)
        except ValueError as e:
            raise InvalidRequestError(f"Invalid base selector: {e}") from e
    for field in schema.get("fields", []):
        field_selector = field.get("selector", "")
        if field_selector:
            try:
                _validate_css_selector(field_selector)
            except ValueError as e:
                raise InvalidRequestError(f"Invalid field selector: {e}") from e

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
