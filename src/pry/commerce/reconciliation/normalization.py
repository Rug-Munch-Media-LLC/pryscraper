"""Pry — reconciliation record normalization."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import math
import re
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from .schemas import Schema

MAX_STRING_LENGTH: Final = 1000
FieldMap = dict[str, str]
logger = logging.getLogger(__name__)


def _build_field_map(schema: Schema) -> dict[str, str]:
    """Build a field mapping from common variations to schema fields."""
    schema_fields = list(schema["fields"].keys())
    field_map: dict[str, str] = {}

    alias_map = {
        "name": ["title", "product_name", "item_name", "listing_title"],
        "price": ["cost", "amount", "sale_price", "current_price", "listing_price"],
        "description": ["desc", "details", "summary", "about", "overview"],
        "url": ["link", "href", "product_url", "page_url"],
        "image_url": ["image", "img", "picture", "photo", "thumbnail"],
        "sku": ["id", "product_id", "item_id", "code", "asin"],
        "availability": ["stock", "in_stock", "status"],
        "brand": ["manufacturer", "vendor", "seller", "make"],
        "rating": ["stars", "score", "average_rating", "review_score"],
        "review_count": ["reviews", "num_reviews", "total_reviews"],
        "address": ["location", "full_address", "property_address"],
    }

    for field in schema_fields:
        field_map[field] = field
        aliases = alias_map.get(field, [])
        for alias in aliases:
            field_map[alias] = field

    return field_map


def _normalize_record(
    record: dict[str, Any],
    field_map: dict[str, str],
    schema: Schema,
) -> dict[str, Any]:
    """Normalize a record to the unified schema."""
    normalized: dict[str, Any] = {}
    source = record.get("_source", record.get("source", "unknown"))
    normalized["_source"] = source
    normalized["_raw"] = {k: v for k, v in record.items() if not k.startswith("_")}

    schema_fields = schema["fields"]
    for raw_key, raw_value in record.items():
        if raw_key.startswith("_"):
            continue
        mapped = field_map.get(raw_key.lower(), raw_key)
        if mapped in schema_fields:
            field_config = schema_fields[mapped]
            converted = _convert_type(raw_value, field_config["type"])
            if converted is not None or field_config.get("required"):
                normalized[mapped] = converted

    for field, config in schema_fields.items():
        if field not in normalized and "default" in config:
            normalized[field] = config["default"]

    return normalized


def _convert_type(value: Any, target_type: str) -> Any:
    """Convert a value to the target type."""
    if value is None:
        return None
    try:
        if target_type == "float":
            if isinstance(value, (int, float)):
                converted = float(value)
                return converted if math.isfinite(converted) else None
            cleaned = re.sub(r"[^\d.,]", "", str(value))
            cleaned = cleaned.replace(",", ".")
            converted = float(cleaned) if cleaned else None
            return converted if converted is not None and math.isfinite(converted) else None
        if target_type == "int":
            if isinstance(value, (int, float)):
                if isinstance(value, float) and not math.isfinite(value):
                    return None
                return int(value)
            cleaned = re.sub(r"[^\d\-]", "", str(value))
            return int(cleaned) if cleaned else None
        if target_type == "str":
            return str(value).strip()[:MAX_STRING_LENGTH]
        if target_type == "bool":
            if isinstance(value, bool):
                return value
            return (
                value.lower() in ("true", "yes", "1", "available", "in stock")
                if isinstance(value, str)
                else bool(value)
            )
    except (ValueError, TypeError, AttributeError, OverflowError):
        logger.debug("reconciliation_conversion_failed", exc_info=True)
        return None
    return value


__all__ = ["MAX_STRING_LENGTH", "_build_field_map", "_convert_type", "_normalize_record"]
