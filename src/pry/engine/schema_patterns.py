"""Free pattern extraction: JSON-LD, meta tags and text heuristics.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Common aliases per schema field, used to look a field up inside JSON-LD.
_JSONLD_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "headline", "title"),
    "title": ("name", "headline", "title"),
    "price": ("price", "lowPrice", "highPrice"),
    "description": ("description", "articleBody", "abstract"),
    "author": ("author", "creator", "byArtist"),
    "date": ("datePublished", "uploadDate", "startDate"),
    "image": ("image", "thumbnailUrl", "logo"),
    "url": ("url", "@id", "mainEntityOfPage"),
}


def extract_from_jsonld(html: str, schema: dict[str, str], data: dict[str, Any]) -> None:
    """Fill ``data`` from JSON-LD structured items (best-effort, never raises)."""
    if not html:
        return
    try:
        from pry.engine.schema_extraction import SchemaExtractor as JsonLdExtractor

        jsonld_items = JsonLdExtractor().extract_jsonld(html)
        for field in schema:
            if field in data:
                continue
            for item in jsonld_items:
                val = jsonld_lookup(item, field)
                if val is not None:
                    data[field] = val
                    break
    except Exception as exc:  # noqa: BLE001 — best-effort source
        logger.debug("schema_extract_jsonld_failed", extra={"error": str(exc)[:120]})


def extract_from_meta(html: str, schema: dict[str, str], data: dict[str, Any]) -> None:
    """Fill ``data`` from <meta> tags (description, og:*, twitter:*)."""
    if not html:
        return
    meta = meta_tags(html)
    for field in schema:
        if field in data:
            continue
        for key in (field, f"og:{field}", f"twitter:{field}"):
            if key in meta:
                data[field] = meta[key]
                break


def extract_from_heuristics(content: str, schema: dict[str, str], data: dict[str, Any]) -> None:
    """Fill ``data`` from the existing text-pattern extractor (best-effort)."""
    missing = [f for f in schema if f not in data]
    if not missing or not content:
        return
    try:
        from pry.engine.extractor import SchemaExtractor

        heur = SchemaExtractor()._pattern_extract(content, {f: schema[f] for f in missing})
        data.update(heur)
    except Exception as exc:  # noqa: BLE001 — best-effort source
        logger.debug("schema_extract_heuristic_failed", extra={"error": str(exc)[:120]})


def pattern_extract(html: str, content: str, schema: dict[str, str]) -> dict[str, Any]:
    """Free pattern extraction: JSON-LD, meta tags, then text heuristics."""
    data: dict[str, Any] = {}
    if not schema:
        return data
    extract_from_jsonld(html, schema, data)
    extract_from_meta(html, schema, data)
    extract_from_heuristics(content, schema, data)
    return data


def jsonld_lookup(item: dict[str, Any], field: str) -> Any | None:
    """Look up a schema field inside one JSON-LD item (with common aliases)."""
    keys = _JSONLD_ALIASES.get(field, (field,))
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


def meta_tags(html: str) -> dict[str, str]:
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


__all__ = [
    "extract_from_heuristics",
    "extract_from_jsonld",
    "extract_from_meta",
    "jsonld_lookup",
    "meta_tags",
    "pattern_extract",
]
