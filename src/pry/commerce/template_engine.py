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


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


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
            logger.warning("template_engine_suppressed", exc_info=True)
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
        logger.warning("template_engine_suppressed", exc_info=True)
        return None


async def execute_template(template_id: str, url: str, **options: Any) -> dict[str, Any]:
    """Execute a scraper template against a URL.

    Every failure is returned with a machine-readable ``code``; unexpected
    errors are logged and surfaced rather than converted into a silent
    success with empty data.
    """
    try:
        return await _execute_template(template_id, url, **options)
    except Exception as e:
        logger.exception("template_execution_failed", extra={"template_id": template_id})
        return {
            "success": False,
            "code": "execution_error",
            "error": f"Template execution failed: {e}",
        }


async def _fetch_html(url: str, schema: dict[str, Any]) -> tuple[str, str]:
    from pry.engine.scraper import PryScraper

    scraper = PryScraper()

    def _html(r: dict[str, Any]) -> str:
        return next((r[k] for k in ("raw_html", "html", "content") if r.get(k)), "")

    res = await scraper.scrape(url, {"bypass_cloudflare": True})
    if res.get("status") == "ok":
        html, err = _html(res), ""
    else:
        html, err = "", res.get("error", "")
    if not html or (len(html) > 500 and not JsonCssExtractionStrategy(schema).extract(html)):
        js = await scraper.scrape(url, {"bypass_cloudflare": True, "js_render": True})
        if js.get("status") == "ok" and len(_html(js)) > len(html):
            html = _html(js)
        elif not html and not err:
            err = js.get("error", "Scrape failed")
    return html, err


def _result(
    template_id: str, template: dict[str, Any], url: str, items: list[Any]
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "template_id": template_id,
        "template_name": template.get("name", ""),
        "url": url,
        "items": items,
        "count": len(items),
        "extracted_at": _now_iso(),
    }
    if not items:
        data["warning"] = "No items matched the CSS selectors. The page structure may have changed."
    return {"success": True, "data": data}


async def _execute_template(template_id: str, url: str, **options: Any) -> dict[str, Any]:
    template = get_template(template_id)
    if not template:
        return {"success": False, "error": f"Template not found: {template_id}"}
    schema = template.get("schema", {})
    if not schema:
        return {"success": False, "error": "Template has no extraction schema"}
    html, err = await _fetch_html(url, schema)
    if not html:
        return {"success": False, "error": err or "No HTML content scraped"}
    return _result(template_id, template, url, JsonCssExtractionStrategy(schema).extract(html))
