"""Pry — CSS/XPath-based structured extraction (no LLM needed)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import re
from typing import Any

from lxml import html as lxml_html
from lxml.etree import ParserError as _LxmlParserError

logger = logging.getLogger(__name__)


class JsonCssExtractionStrategy:
    """Extract structured JSON from HTML using CSS selectors / XPath.

    Schema format:
    {
        "name": "items",
        "base_selector": "css-selector",
        "fields": [
            {"name": "title", "selector": "h3", "type": "text"},
            {"name": "link", "selector": "a", "type": "attribute", "attribute": "href"},
            {"name": "price", "selector": ".price", "type": "text", "transform": "strip_currency"},
            {"name": "nested", "type": "nested", "fields": [...]},
        ]
    }

    Field types: text, attribute, html, nested, count, exists, regex
    """

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self.name = schema.get("name", "extracted")

    def extract(self, html: str) -> list[dict[str, Any]]:
        """Extract structured data from HTML string."""
        try:
            tree = lxml_html.fromstring(html)
        except _LxmlParserError:
            return []
        base_selector = self.schema.get("base_selector")
        fields = self.schema.get("fields", [])

        elements = tree.cssselect(base_selector) if base_selector else [tree]

        results = []
        for el in elements:
            row = self._extract_fields(el, fields)
            if any(v not in (None, "", []) for v in row.values()):
                results.append(row)

        return results

    def _extract_fields(self, element: Any, fields: list[dict[str, Any]]) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for field in fields:
            name = field["name"]
            ftype = field.get("type", "text")
            selector = field.get("selector", "")
            attr = field.get("attribute", "")
            transform = field.get("transform", "")

            try:
                if ftype == "nested":
                    sub_el = element.cssselect(selector)[0] if selector else element
                    row[name] = self._extract_fields(sub_el, field.get("fields", []))
                elif ftype == "count":
                    row[name] = len(element.cssselect(selector))
                elif ftype == "exists":
                    row[name] = len(element.cssselect(selector)) > 0
                elif ftype == "regex":
                    text = self._get_text(element, selector)
                    pattern = field.get("pattern", "")
                    match = re.search(pattern, text) if pattern else None
                    row[name] = match.group(1) if match else None
                elif ftype == "attribute":
                    els = element.cssselect(selector) if selector else [element]
                    values = []
                    for e in els:
                        v = e.get(attr, "")
                        if v:
                            values.append(self._apply_transform(v.strip(), transform))
                    row[name] = values[0] if len(values) == 1 else values if values else None
                elif ftype == "html":
                    els = element.cssselect(selector) if selector else [element]
                    row[name] = "\n".join(lxml_html.tostring(e, encoding="unicode") for e in els)
                else:
                    text = self._get_text(element, selector)
                    row[name] = self._apply_transform(text, transform)
            except Exception as e:  # noqa: BLE001
                logger.warning("field_extract_failed", extra={"field": name, "error": str(e)})
                row[name] = None

        return row

    def _get_text(self, element: Any, selector: str) -> str:
        if selector:
            els = element.cssselect(selector)
            if not els:
                return ""
            return str(" ".join(str(e.text_content()).strip() for e in els))
        return str(element.text_content()).strip()

    def _apply_transform(self, value: str, transform: str) -> Any:
        if not value:
            return value
        if transform == "strip_currency":
            return re.sub(r"[^\d.,]", "", value).strip()
        if transform == "lower":
            return value.lower()
        if transform == "upper":
            return value.upper()
        if transform == "strip":
            return value.strip()
        if transform == "int":
            try:
                return int(re.sub(r"[^\d\-]", "", value))
            except ValueError:
                return value
        if transform == "float":
            try:
                return float(re.sub(r"[^\d.\-]", "", value))
            except ValueError:
                return value
        return value


async def extract_structured(
    html: str,
    schema: dict[str, Any],
    extraction_type: str = "css",
) -> list[dict[str, Any]]:
    """Extract structured data using the specified strategy."""
    if extraction_type == "css":
        strategy = JsonCssExtractionStrategy(schema)
        return strategy.extract(html)
    raise ValueError(f"Unknown extraction type: {extraction_type}")


__all__ = ["JsonCssExtractionStrategy", "extract_structured"]
