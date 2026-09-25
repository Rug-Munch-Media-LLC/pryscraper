"""Best-effort LLM enhancement for entity reconciliation."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import math
from contextlib import suppress
from typing import Any

from .reporting import build_reconciliation_report

logger = logging.getLogger(__name__)
_MAX_LOW_CONFIDENCE_GROUPS = 25


async def llm_enhance_reconciliation(
    entities: list[dict[str, Any]], low_confidence_threshold: float = 0.5
) -> dict[str, Any]:
    """Verify a bounded set of low-confidence groups with best-effort LLM calls."""
    processed_groups = 0
    try:
        threshold = float(low_confidence_threshold)
        if isinstance(low_confidence_threshold, bool) or not math.isfinite(threshold):
            raise ValueError("invalid_threshold")
        threshold = min(1.0, max(0.0, threshold))

        groups: dict[str, list[dict[str, Any]]] = {}
        for index, entity in enumerate(entities):
            if not isinstance(entity, dict):
                continue
            raw_confidence = entity.get("confidence", 1.0)
            if isinstance(raw_confidence, bool):
                continue
            try:
                confidence = float(raw_confidence)
            except (TypeError, ValueError, OverflowError):
                logger.debug("reconciliation_confidence_invalid", exc_info=True)
                continue
            if not math.isfinite(confidence) or confidence >= threshold:
                continue

            raw_group_id = entity.get("group_id", entity.get("id", ""))
            if raw_group_id is None:
                group_id = ""
            elif isinstance(raw_group_id, (str, int, float, bool)):
                group_id = str(raw_group_id)
            else:
                group_id = f"invalid-{index}"
            if group_id not in groups:
                if len(groups) >= _MAX_LOW_CONFIDENCE_GROUPS:
                    continue
                groups[group_id] = []
            groups[group_id].append(entity)

        if not groups:
            return {
                "llm_enhanced": False,
                "verified": 0,
                "refuted": 0,
                "low_confidence_groups": 0,
            }

        from pry.api.llm_features import llm_entity_reconcile

        verified = 0
        refuted = 0
        for group in groups.values():
            result = await llm_entity_reconcile(group, vertical="product")
            if not isinstance(result, dict) or not isinstance(result.get("is_same_entity"), bool):
                raise TypeError("invalid_llm_result")
            if result["is_same_entity"]:
                verified += 1
            else:
                refuted += 1
            processed_groups += 1
        return {
            "llm_enhanced": True,
            "verified": verified,
            "refuted": refuted,
            "low_confidence_groups": len(groups),
        }
    except Exception as exc:  # noqa: BLE001 - best-effort public boundary
        with suppress(Exception):
            logger.debug(
                "llm_reconciliation_failed",
                extra={
                    "error_type": type(exc).__name__,
                    "processed_groups": processed_groups,
                },
            )
        return {"llm_enhanced": False, "error": "LLM reconciliation unavailable"}


async def reconcile(
    records: list[dict[str, Any]],
    vertical: str,
    threshold: float = 0.7,
) -> dict[str, Any]:
    """Run reconciliation and always return the established response shape."""
    try:
        from pry.commerce.reconciliation import match_entities

        entities = match_entities(records, vertical, threshold)
        if not isinstance(entities, list):
            try:
                entities = list(entities)
            except TypeError:
                logger.debug("reconciliation_entities_invalid", exc_info=True)
                entities = []
        return {
            "entities": entities,
            "report": build_reconciliation_report(entities, vertical),
        }
    except Exception as exc:  # noqa: BLE001 - stable public response required
        with suppress(Exception):
            logger.warning(
                "reconciliation_pipeline_failed",
                extra={"error_type": type(exc).__name__},
            )
        return {
            "entities": [],
            "report": build_reconciliation_report([], vertical),
        }
