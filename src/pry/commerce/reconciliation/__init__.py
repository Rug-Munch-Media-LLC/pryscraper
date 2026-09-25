"""Stable entity-reconciliation facade with focused matching modules."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from .llm import llm_enhance_reconciliation, reconcile
from .matching import (
    _compute_entity_id,
    _compute_group_confidence,
    _records_match,
    compute_similarity,
    match_entities,
)
from .normalization import (
    _build_field_map,
    _convert_type,
    _normalize_record,
)
from .reporting import build_reconciliation_report
from .schemas import VERTICAL_SCHEMAS

__all__ = [
    "VERTICAL_SCHEMAS",
    "_build_field_map",
    "_compute_entity_id",
    "_compute_group_confidence",
    "_convert_type",
    "_normalize_record",
    "_records_match",
    "build_reconciliation_report",
    "compute_similarity",
    "llm_enhance_reconciliation",
    "match_entities",
    "reconcile",
]
