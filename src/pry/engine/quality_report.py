"""Anomaly detection orchestration for extracted-data quality.

Split out of ``pry.engine.quality``: this module decides which detection
steps run and in what order; the rules themselves live in
``quality_anomaly_rules``. ``quality.detect_anomalies`` re-exports
``detect_anomalies`` so existing import paths keep working.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from pry.engine.quality_anomaly_rules import (
    common_field_anomalies,
    missing_field_anomalies,
    new_field_anomalies,
)

_EMPTY_RESULT_ANOMALY = {
    "type": "empty_result",
    "severity": "critical",
    "field": "*",
    "message": "Extraction returned empty — previous run had data",
}


def detect_anomalies(
    current_data: dict[str, Any],
    previous_data: dict[str, Any] | None = None,
    z_score_threshold: float = 2.0,
) -> list[dict[str, Any]]:
    """Detect anomalies in extracted data compared to previous runs.

    Flags:
    - Missing fields (field present before, absent now)
    - New fields (field absent before, present now)
    - Value type changes
    - Large value swings (for numeric fields)
    - Empty results when previous had data
    """
    if previous_data is None:
        return []

    if not current_data and previous_data:
        return [dict(_EMPTY_RESULT_ANOMALY)]

    if not isinstance(current_data, dict) or not isinstance(previous_data, dict):
        return []

    anomalies = missing_field_anomalies(previous_data, current_data)
    anomalies += new_field_anomalies(previous_data, current_data)
    anomalies += common_field_anomalies(previous_data, current_data, z_score_threshold)
    return anomalies
