"""Reconciliation dashboard reporting."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import math
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)


def build_reconciliation_report(
    entities: list[dict[str, Any]],
    vertical: str,
) -> dict[str, Any]:
    """Build a dashboard report while tolerating malformed entity rows."""
    rows: list[tuple[int, float, set[str]]] = []
    unique_sources: set[str] = set()

    entity_iter = entities
    with suppress(Exception):
        for entity in entity_iter:
            if not isinstance(entity, dict):
                continue
            try:
                raw_count = entity.get("record_count", 0)
                count = 0 if isinstance(raw_count, bool) else max(0, int(raw_count))
            except (TypeError, ValueError, OverflowError):
                logger.debug("reconciliation_record_count_invalid", exc_info=True)
                count = 0
            try:
                raw_confidence = entity.get("confidence", 0.0)
                confidence = 0.0 if isinstance(raw_confidence, bool) else float(raw_confidence)
            except (TypeError, ValueError, OverflowError):
                logger.debug("reconciliation_confidence_invalid", exc_info=True)
                confidence = 0.0
            if not math.isfinite(confidence):
                confidence = 0.0
            confidence = min(1.0, max(0.0, confidence))

            raw_sources = entity.get("sources", [])
            sources = (raw_sources,) if isinstance(raw_sources, str) else raw_sources
            try:
                row_sources = {source for source in sources if isinstance(source, str) and source}
            except TypeError:
                logger.debug("reconciliation_sources_invalid", exc_info=True)
                row_sources = set()
            rows.append((count, confidence, row_sources))
            unique_sources.update(row_sources)

    total_records = sum(count for count, _, _ in rows)
    matched_entities = sum(count > 1 for count, _, _ in rows)
    unmatched_records = sum(count == 1 for count, _, _ in rows)
    high_confidence = sum(confidence >= 0.8 for _, confidence, _ in rows)
    low_confidence = sum(confidence < 0.5 for _, confidence, _ in rows)

    schema: dict[str, Any]
    try:
        from pry.commerce.reconciliation import VERTICAL_SCHEMAS

        schema = VERTICAL_SCHEMAS.get(vertical, {})
    except (AttributeError, ImportError, TypeError):
        logger.debug("reconciliation_schema_unavailable", exc_info=True)
        schema = {}

    return {
        "vertical": vertical,
        "total_entities": len(rows),
        "total_records": total_records,
        "matched_entities": matched_entities,
        "unmatched_records": unmatched_records,
        "match_rate": round(matched_entities / max(len(rows), 1) * 100, 1),
        "high_confidence": high_confidence,
        "low_confidence": low_confidence,
        "unique_sources": list(unique_sources),
        "schema": schema,
    }
