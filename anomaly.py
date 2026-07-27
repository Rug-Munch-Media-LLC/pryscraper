# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Real anomaly detection. Multi-field, time-series aware, with seasonality support."""

import logging
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Real anomaly detection with multiple algorithms."""

    def __init__(self, sensitivity: float = 2.0):
        self.sensitivity = sensitivity

    def detect(
        self,
        historical: list[dict[str, Any]],
        current: dict[str, Any],
        fields: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Detect anomalies across multiple fields with time-series awareness.

        Args:
            historical: List of historical snapshots, newest last
            current: Current snapshot
            fields: Specific fields to check (None = check all common numeric fields)
            context: Additional context (e.g., day_of_week, is_promotional_period)
        """
        if not historical or not current:
            return {"anomalies": [], "is_anomaly": False, "reason": "Insufficient data"}

        if fields is None:
            fields = self._common_fields([*historical, current])

        anomalies: list[dict[str, Any]] = []
        context = context or {}

        for field in fields:
            values: list[float] = [
                float(h[field]) for h in historical if isinstance(h.get(field), (int, float))
            ]
            current_val = current.get(field)

            if current_val is None or len(values) < 3:
                continue
            if not isinstance(current_val, (int, float)):
                continue

            stat_result = self._statistical_detection(values, current_val, field)
            if stat_result["is_anomaly"]:
                anomalies.append(stat_result)

            seasonal_result = self._seasonality_detection(values, current_val, field, context)
            if seasonal_result.get("seasonal_anomaly"):
                anomalies.append(seasonal_result)

            correlated = self._correlate_with_other_fields(historical, current, field)
            if correlated is not None:
                anomalies.append(correlated)

        return {
            "is_anomaly": len(anomalies) > 0,
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "checked_fields": fields,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    def _common_fields(self, records: list[dict[str, Any]]) -> list[str]:
        """Find numeric fields present in all records."""
        if not records:
            return []
        common: set[str] = set()
        for k, v in records[0].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                common.add(k)
        for r in records[1:]:
            rkeys = {
                k for k, v in r.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
            common &= rkeys
        return list(common)

    def _statistical_detection(
        self, values: list[float], current: float, field: str
    ) -> dict[str, Any]:
        """Z-score based detection with confidence."""
        if len(values) < 3:
            return {"is_anomaly": False, "field": field}
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0
        if stdev == 0:
            if values[-1] == current:
                return {"is_anomaly": False, "field": field}
            return {
                "is_anomaly": True,
                "field": field,
                "type": "value_change",
                "reason": f"Value changed from constant {mean} to {current}",
                "severity": "medium",
            }

        z_score = abs((current - mean) / stdev)
        is_anomaly = z_score > self.sensitivity
        change_pct = ((current - mean) / mean) * 100 if mean != 0 else 0
        severity = "high" if z_score > 3.0 else "medium" if z_score > 2.0 else "low"
        return {
            "is_anomaly": is_anomaly,
            "field": field,
            "type": "statistical",
            "z_score": round(z_score, 2),
            "mean": round(mean, 2),
            "stdev": round(stdev, 2),
            "change_pct": round(change_pct, 1),
            "severity": severity,
            "reason": f"Z-score {round(z_score, 2)} exceeds threshold {self.sensitivity}",
        }

    def _seasonality_detection(
        self,
        values: list[float],
        current: float,
        field: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Detect if a change is explainable by seasonality (e.g., weekend, holiday)."""
        if len(values) < 7:
            return {"seasonal_anomaly": False}
        dow_values: dict[int, list[float]] = defaultdict(list)
        for i, v in enumerate(values):
            dow = i % 7
            dow_values[dow].append(v)
        current_dow = len(values) % 7
        if current_dow in dow_values and len(dow_values[current_dow]) >= 2:
            dow_mean = statistics.mean(dow_values[current_dow])
            dow_stdev = (
                statistics.stdev(dow_values[current_dow]) if len(dow_values[current_dow]) > 1 else 0
            )
            if dow_stdev > 0 and abs((current - dow_mean) / dow_stdev) < 1.5:
                return {
                    "seasonal_anomaly": False,
                    "seasonal_explanation": (
                        f"Value fits "
                        f"{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][current_dow]} pattern"
                    ),
                }
        if context.get("is_promotional"):
            return {
                "seasonal_anomaly": False,
                "seasonal_explanation": "Promotional period - changes expected",
            }
        return {"seasonal_anomaly": False}

    def _correlate_with_other_fields(
        self, historical: list[dict], current: dict, field: str
    ) -> dict[str, Any] | None:
        """Check if a field change is correlated with changes in other fields.
        E.g., if price dropped 20% but discount_pct went from 0 to 20%, the drop is explained."""
        if len(historical) < 2:
            return None
        prev = historical[-1]
        for other_field in current:
            if other_field == field or other_field not in prev:
                continue
            cur_other = current.get(other_field)
            prev_other = prev.get(other_field)
            if (
                isinstance(cur_other, (int, float))
                and isinstance(prev_other, (int, float))
                and cur_other != prev_other
                and current[field] != prev.get(field)
            ):
                return {
                    "is_anomaly": False,
                    "field": field,
                    "type": "correlated",
                    "explanation": f"Change in {field} correlates with change in {other_field}",
                }
        return None
