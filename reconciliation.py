"""Pry — Multi-Source Entity Reconciliation.
Cross-source entity matching, unified schema mapping, diff dashboard."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import difflib
import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Vertical Schemas ──

VERTICAL_SCHEMAS: dict[str, dict[str, Any]] = {
    "product": {
        "name": "Product",
        "fields": {
            "name": {"type": "str", "required": True, "description": "Product name"},
            "price": {"type": "float", "required": True, "description": "Current price"},
            "original_price": {
                "type": "float",
                "required": False,
                "description": "Original/MSRP price",
            },
            "currency": {
                "type": "str",
                "required": False,
                "default": "USD",
                "description": "Currency code",
            },
            "availability": {
                "type": "str",
                "required": False,
                "description": "in_stock, out_of_stock, pre_order",
            },
            "brand": {"type": "str", "required": False, "description": "Brand/manufacturer"},
            "sku": {"type": "str", "required": False, "description": "Product SKU or ID"},
            "url": {"type": "str", "required": True, "description": "Product URL"},
            "image_url": {"type": "str", "required": False, "description": "Product image URL"},
            "description": {"type": "str", "required": False, "description": "Product description"},
            "rating": {"type": "float", "required": False, "description": "Average rating (0-5)"},
            "review_count": {"type": "int", "required": False, "description": "Number of reviews"},
            "category": {"type": "str", "required": False, "description": "Product category"},
        },
        "identity_fields": ["name", "sku", "url"],
    },
    "job": {
        "name": "Job Posting",
        "fields": {
            "title": {"type": "str", "required": True, "description": "Job title"},
            "company": {"type": "str", "required": True, "description": "Company name"},
            "location": {"type": "str", "required": False, "description": "Job location"},
            "salary_min": {"type": "float", "required": False, "description": "Minimum salary"},
            "salary_max": {"type": "float", "required": False, "description": "Maximum salary"},
            "salary_currency": {"type": "str", "required": False, "default": "USD"},
            "description": {"type": "str", "required": False, "description": "Job description"},
            "url": {"type": "str", "required": True, "description": "Job posting URL"},
            "posted_date": {"type": "str", "required": False, "description": "Posted date"},
            "job_type": {
                "type": "str",
                "required": False,
                "description": "Full-time, part-time, contract",
            },
        },
        "identity_fields": ["title", "company"],
    },
    "real_estate": {
        "name": "Real Estate Listing",
        "fields": {
            "address": {"type": "str", "required": True, "description": "Property address"},
            "price": {"type": "float", "required": True, "description": "Listing price"},
            "bedrooms": {"type": "int", "required": False, "description": "Number of bedrooms"},
            "bathrooms": {"type": "float", "required": False, "description": "Number of bathrooms"},
            "sqft": {"type": "int", "required": False, "description": "Square footage"},
            "property_type": {
                "type": "str",
                "required": False,
                "description": "House, condo, apartment",
            },
            "url": {"type": "str", "required": True, "description": "Listing URL"},
            "description": {"type": "str", "required": False, "description": "Listing description"},
        },
        "identity_fields": ["address"],
    },
    "review": {
        "name": "Review",
        "fields": {
            "product_name": {
                "type": "str",
                "required": True,
                "description": "Product being reviewed",
            },
            "rating": {"type": "int", "required": True, "description": "Rating (1-5)"},
            "title": {"type": "str", "required": False, "description": "Review title"},
            "body": {"type": "str", "required": False, "description": "Review text"},
            "author": {"type": "str", "required": False, "description": "Review author"},
            "date": {"type": "str", "required": False, "description": "Review date"},
            "url": {"type": "str", "required": True, "description": "Review URL"},
        },
        "identity_fields": ["product_name", "author", "title"],
    },
}


# ── Entity Matching ──


def compute_similarity(a: str, b: str) -> float:
    """Compute string similarity (0-1) using multiple methods."""
    if not a or not b:
        return 0.0

    a_lower = a.lower().strip()
    b_lower = b.lower().strip()

    if a_lower == b_lower:
        return 1.0

    a_tokens = set(re.findall(r"\w+", a_lower))
    b_tokens = set(re.findall(r"\w+", b_lower))
    if a_tokens and b_tokens:
        jaccard = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
        if jaccard >= 0.6:
            return jaccard

    ratio = difflib.SequenceMatcher(None, a_lower, b_lower).ratio()
    return ratio


def match_entities(
    records: list[dict[str, Any]],
    vertical: str,
    threshold: float = 0.7,
) -> list[dict[str, Any]]:
    """Match records from multiple sources into unified entities.

    Args:
        records: Records from multiple sources
        vertical: One of: product, job, real_estate, review
        threshold: Similarity threshold for matching (0-1)

    Returns list of entity groups with matched records.
    """
    schema = VERTICAL_SCHEMAS.get(vertical)
    if not schema:
        raise ValueError(
            f"Unknown vertical: {vertical}. Supported: {list(VERTICAL_SCHEMAS.keys())}"
        )

    identity_fields = schema["identity_fields"]
    field_map = _build_field_map(schema)

    normalized = [_normalize_record(r, field_map, schema) for r in records]

    entities: list[dict[str, Any]] = []
    assigned: set[int] = set()

    for i, record in enumerate(normalized):
        if i in assigned:
            continue

        group: list[dict[str, Any]] = [record]
        assigned.add(i)
        entity_id = _compute_entity_id(record, identity_fields)

        for j, other in enumerate(normalized):
            if j in assigned:
                continue
            if _records_match(record, other, identity_fields, threshold):
                group.append(other)
                assigned.add(j)

        entities.append(
            {
                "entity_id": entity_id,
                "confidence": _compute_group_confidence(group, identity_fields),
                "records": group,
                "record_count": len(group),
                "sources": list({r.get("_source", "unknown") for r in group}),
            }
        )

    return entities


def _build_field_map(schema: dict[str, Any]) -> dict[str, str]:
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
    schema: dict[str, Any],
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
                return float(value)
            cleaned = re.sub(r"[^\d.,]", "", str(value))
            cleaned = cleaned.replace(",", ".")
            return float(cleaned) if cleaned else None
        if target_type == "int":
            if isinstance(value, (int, float)):
                return int(value)
            cleaned = re.sub(r"[^\d\-]", "", str(value))
            return int(cleaned) if cleaned else None
        if target_type == "str":
            return str(value).strip()[:1000]
        if target_type == "bool":
            if isinstance(value, bool):
                return value
            return (
                value.lower() in ("true", "yes", "1", "available", "in stock")
                if isinstance(value, str)
                else bool(value)
            )
    except (ValueError, TypeError, AttributeError):
        return None
    return value


def _records_match(
    a: dict[str, Any],
    b: dict[str, Any],
    identity_fields: list[str],
    threshold: float,
) -> bool:
    """Check if two records match based on identity fields."""
    scores = []
    for field in identity_fields:
        val_a = a.get(field)
        val_b = b.get(field)
        if val_a and val_b:
            sim = compute_similarity(str(val_a), str(val_b))
            scores.append(sim)

    if not scores:
        return False

    avg = sum(scores) / len(scores)
    return avg >= threshold


def _compute_entity_id(record: dict[str, Any], identity_fields: list[str]) -> str:
    """Compute a stable entity ID from identity fields."""
    parts = []
    for field in identity_fields:
        val = record.get(field, "")
        parts.append(str(val).lower().strip()[:50])
    raw = "-".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _compute_group_confidence(
    group: list[dict[str, Any]],
    identity_fields: list[str],
) -> float:
    """Compute confidence score for an entity group."""
    if len(group) == 1:
        return 0.5

    scores = []
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            if _records_match(group[i], group[j], identity_fields, 0.0):
                scores.append(1.0)

    if not scores:
        return 0.5

    base = sum(scores) / len(scores)
    source_bonus = min(0.3, (len(group) - 1) * 0.1)
    return round(min(1.0, base + source_bonus), 2)


# ── Reconciliation Dashboard ──


def build_reconciliation_report(
    entities: list[dict[str, Any]],
    vertical: str,
) -> dict[str, Any]:
    """Build a reconciliation report for the dashboard."""
    total_records = sum(e["record_count"] for e in entities)
    matched_entities = [e for e in entities if e["record_count"] > 1]
    single_records = [e for e in entities if e["record_count"] == 1]
    high_confidence = sum(1 for e in entities if e["confidence"] >= 0.8)
    low_confidence = sum(1 for e in entities if e["confidence"] < 0.5)

    return {
        "vertical": vertical,
        "total_entities": len(entities),
        "total_records": total_records,
        "matched_entities": len(matched_entities),
        "unmatched_records": len(single_records),
        "match_rate": round(len(matched_entities) / max(len(entities), 1) * 100, 1),
        "high_confidence": high_confidence,
        "low_confidence": low_confidence,
        "unique_sources": list({s for e in entities for s in e.get("sources", [])}),
        "schema": VERTICAL_SCHEMAS.get(vertical, {}),
    }


# ── API helpers ──


async def llm_enhance_reconciliation(
    entities: list[dict[str, Any]], low_confidence_threshold: float = 0.5
) -> dict[str, Any]:
    """Use the LLM to verify or refute low-confidence entity matches.

    For each entity group whose field-based confidence is below the threshold,
    ask the LLM whether the records actually refer to the same entity. This
    catches cases where the field-based reconciliation was wrong (e.g., two
    different products with similar names that aren't actually the same).

    Best-effort: if the LLM call fails, returns the input unchanged with
    `llm_enhanced: False`.
    """
    try:
        from llm_features import llm_entity_reconcile

        low_conf = [e for e in entities if e.get("confidence", 1.0) < low_confidence_threshold]
        if not low_conf:
            return {"llm_enhanced": False, "verified": 0, "refuted": 0, "low_confidence_groups": 0}
        # Group low-confidence records by their group_id (assuming each entity has one)
        groups: dict[str, list[dict]] = {}
        for e in low_conf:
            gid = e.get("group_id", e.get("id", ""))
            groups.setdefault(gid, []).append(e)
        verified = 0
        refuted = 0
        for gid, group in groups.items():
            result = await llm_entity_reconcile(group, vertical="product")
            if result.get("is_same_entity"):
                verified += 1
            else:
                refuted += 1
        return {
            "llm_enhanced": True,
            "verified": verified,
            "refuted": refuted,
            "low_confidence_groups": len(groups),
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("llm_reconciliation_failed", extra={"error": str(e)[:80]})
        return {"llm_enhanced": False, "error": str(e)[:200]}


async def reconcile(
    records: list[dict[str, Any]],
    vertical: str,
    threshold: float = 0.7,
) -> dict[str, Any]:
    """Full reconciliation pipeline: match + normalize + report."""
    entities = match_entities(records, vertical, threshold)
    report = build_reconciliation_report(entities, vertical)
    return {
        "entities": entities,
        "report": report,
    }
