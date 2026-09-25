"""Deterministic cross-source entity matching for commerce reconciliation.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

import difflib
import hashlib
import re
from typing import Any

from .normalization import _build_field_map, _normalize_record
from .schemas import VERTICAL_SCHEMAS

MAX_RECORDS = 10_000


def _validate_matching_inputs(
    records: list[dict[str, Any]],
    threshold: float,
) -> None:
    """Reject unsafe matching inputs without changing valid legacy inputs."""
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not 0.0 <= threshold <= 1.0
    ):
        raise ValueError("threshold must be a finite number between 0 and 1")
    if len(records) > MAX_RECORDS:
        raise ValueError(f"records cannot contain more than {MAX_RECORDS} items")


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
    _validate_matching_inputs(records, threshold)

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
