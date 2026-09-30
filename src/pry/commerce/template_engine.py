"""Pry — Template Engine for one-click site-specific scraping.
Loads and executes pre-built extraction schemas for popular websites."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import logging
from pathlib import Path
from typing import Any, cast

from pry.core.pathsafe import safe_join
from pry.engine.extraction import JsonCssExtractionStrategy

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)


def list_templates() -> list[dict[str, Any]]:
    """List all available scraper templates with metadata."""
    templates = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            templates.append(
                {
                    "id": path.stem,
                    "name": data.get("name", path.stem),
                    "description": data.get("description", ""),
                    "site": data.get("site", ""),
                    "category": data.get("category", "general"),
                    "fields": list(data.get("schema", {}).get("fields", [])),
                    "icon": data.get("icon", "🌐"),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return templates


def get_template(template_id: str) -> dict[str, Any] | None:
    """Get a specific template by ID."""
    path = safe_join(TEMPLATES_DIR, template_id, ".json", kind="template_id")
    if not path.exists():
        return None
    try:
        return cast("dict[str, Any]", json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


async def execute_template(template_id: str, url: str, **options: Any) -> dict[str, Any]:
    """Execute a scraper template against a URL.

    This scrapes the URL and extracts structured data using the template's schema.
    """
    template = get_template(template_id)
    if not template:
        return {"success": False, "error": f"Template not found: {template_id}"}

    schema = template.get("schema", {})
    if not schema:
        return {"success": False, "error": "Template has no extraction schema"}

    # Scrape the URL with progressive fallback
    from pry.engine.scraper import PryScraper

    scraper = PryScraper()
    html = ""
    scrape_error = ""

    # Helper: get raw HTML from scraper result
    def _get_html(r):
        for key in ("raw_html", "html", "content"):
            val = r.get(key)
            if val:
                return val
        return ""

    # Tier 1: Try with Cloudflare bypass
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") == "ok":
        html = _get_html(result)
    else:
        scrape_error = result.get("error", "")

    # Quick extraction test — if no items found and JS render available, retry
    if html:
        strategy = JsonCssExtractionStrategy(schema)
        items = strategy.extract(html)
        if not items and len(html) > 500:
            result_js = await scraper.scrape(url, {"bypass_cloudflare": True, "js_render": True})
            if result_js.get("status") == "ok":
                html_js = _get_html(result_js)
                if html_js and len(html_js) > len(html):
                    html = html_js
    else:
        # Tier 2: Try with JS rendering
        result_js = await scraper.scrape(url, {"bypass_cloudflare": True, "js_render": True})
        if result_js.get("status") == "ok":
            html = _get_html(result_js)
        elif not scrape_error:
            scrape_error = result_js.get("error", "Scrape failed")

    if not html:
        return {"success": False, "error": scrape_error or "No HTML content scraped"}

    # Extract using the schema
    strategy = JsonCssExtractionStrategy(schema)
    items = strategy.extract(html)

    if not items:
        return {
            "success": True,
            "data": {
                "template_id": template_id,
                "template_name": template.get("name", ""),
                "url": url,
                "items": [],
                "count": 0,
                "warning": "No items matched the CSS selectors. The page structure may have changed.",
                "extracted_at": __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(),
            },
        }

    return {
        "success": True,
        "data": {
            "template_id": template_id,
            "template_name": template.get("name", ""),
            "url": url,
            "items": items,
            "count": len(items),
            "extracted_at": __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat(),
        },
    }
