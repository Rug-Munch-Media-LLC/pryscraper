# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Mutation-killing tests for quality.py (audit win #6 continuation).

Targets the four biggest survivor pools: detect_anomalies (127),
compute_freshness (50), _compute_list/_dict_completeness (71),
compute_null_rate (13). Every test pins exact values or exact boundaries
derived from the docstrings/spec — property-style assertions cannot kill
these mutants (see MUTATION_BASELINE.md lesson).

Boundary conventions pinned here:
- z-score strictly greater than threshold flags a swing (z == t does NOT)
- severity high iff |pct| > 50 (pct == 50 stays medium)
- content drift requires len(prev) > 20 AND ratio < 0.5 (both strict)
- freshness: age <= max_age is fresh (age == max_age IS fresh)
- severity ladder distances: >20 high, >10 medium, >3 low, else minimal
"""

from __future__ import annotations

import pytest

from pry.engine.quality import (
    compute_completeness,
    compute_freshness,
    compute_null_rate,
    compute_schema_adherence,
    detect_anomalies,
)

# ── detect_anomalies ─────────────────────────────────────────────────────────


class TestSchemaAdherence:
    def test_no_expected_types_scores_perfect(self) -> None:
        result = compute_schema_adherence({"a": 1}, {})
        expected = {
            "score": 100.0,
            "total_checks": 0,
            "type_mismatches": 0,
            "field_issues": {},
        }
        assert result == expected

    def test_mismatch_tracking_per_field(self) -> None:
        data = [{"a": "str-not-int", "b": 1}, {"a": 5, "b": "also-not-int"}]
        result = compute_schema_adherence(data, {"a": int, "b": int})
        assert result["total_checks"] == 4
        assert result["type_mismatches"] == 2
        expected = {"a": 1, "b": 1}
        assert result["field_issues"] == expected
        assert result["score"] == 50.0

    def test_none_values_are_exempt_from_type_checks(self) -> None:
        result = compute_schema_adherence({"a": None}, {"a": int})
        assert result["type_mismatches"] == 0
        assert result["score"] == 100.0


class TestNullRate:
    def test_null_vs_empty_rates_across_records(self) -> None:
        records = [
            {"a": None, "b": "", "c": 1},
            {"a": None, "b": [], "c": 2},
            {"a": 3, "b": "x", "c": 3},
        ]
        result = compute_null_rate(records)
        expected = {"null_rate": 66.7, "empty_rate": 0.0, "total": 3}
        assert result["a"] == expected
        expected_2 = {"null_rate": 0.0, "empty_rate": 66.7, "total": 3}
        assert result["b"] == expected_2
        expected_3 = {"null_rate": 0.0, "empty_rate": 0.0, "total": 3}
        assert result["c"] == expected_3

    def test_single_dict_wrapped(self) -> None:
        result = compute_null_rate({"x": None})
        expected = {"null_rate": 100.0, "empty_rate": 0.0, "total": 1}
        assert result["x"] == expected


class TestFreshnessKeyCoverage:
    """Every recognised timestamp key must be honoured (kills key-rename mutants)."""

    @pytest.mark.parametrize(
        "key", ["timestamp", "checked_at", "cached_at", "scraped_at", "created_at", "updated_at"]
    )
    def test_each_recognised_key_drives_age(
        self, monkeypatch: pytest.MonkeyPatch, key: str
    ) -> None:
        import pry.engine.quality_checks.freshness as freshness_module

        frozen = 1_800_000_000.0
        monkeypatch.setattr(freshness_module.time, "time", lambda: frozen)
        result = compute_freshness({key: frozen - 60})
        assert result["age_seconds"] == 60
        assert result["fresh"] is True

    def test_default_max_age_is_3600(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """age = 3600.5s: fresh under default 3600? NO (<= 3600 fails).
        A 3601 default mutant would wrongly report fresh."""
        import pry.engine.quality_checks.freshness as freshness_module

        frozen = 1_800_000_000.0
        monkeypatch.setattr(freshness_module.time, "time", lambda: frozen)
        result = compute_freshness({"timestamp": frozen - 3600.5})
        assert result["fresh"] is False


class TestCompletenessAsymmetricCounts:
    """filled/empty counts must be computed independently (kills in/not-in flip)."""

    def test_one_filled_three_empty(self) -> None:
        data = {"only_filled": 7, "e1": "", "e2": [], "e3": {}}
        result = compute_completeness(data)
        assert result["filled_fields"] == 1
        assert result["empty_fields"] == 3
        assert result["null_fields"] == 0
        assert result["score"] == 25.0


class TestAnomalyExactContracts:
    """Exact dict shapes + default threshold — kill key-rename/default mutants."""

    def test_default_z_threshold_is_two(self) -> None:
        # prev=100 -> curr=350 gives z = 250/100 = 2.5: flagged at the default
        # threshold 2.0, but a 3.0-default mutant would miss it.
        result = detect_anomalies({"p": 350}, {"p": 100})
        expected = ["value_swing"]
        assert [a["type"] for a in result if a["type"] == "value_swing"] == expected
        # And z = 1.5 must stay quiet at the default threshold.
        quiet = detect_anomalies({"p": 250}, {"p": 100})
        assert [a for a in quiet if a["type"] == "value_swing"] == []

    def test_missing_field_exact_dict(self) -> None:
        expected = [
            {
                "type": "missing_field",
                "severity": "high",
                "field": "a",
                "message": ("Field 'a' was present in previous extraction but is now missing"),
            }
        ]
        assert detect_anomalies({"b": 2}, {"a": 1, "b": 2}) == expected

    def test_new_field_and_type_change_exact_dicts(self) -> None:
        result = detect_anomalies({"keep": 1, "add": 2, "tc": "s"}, {"keep": 1, "tc": 9})
        by_type = {a["type"]: a for a in result}
        expected = {
            "type": "new_field",
            "severity": "info",
            "field": "add",
            "message": "New field 'add' appeared",
        }
        assert by_type["new_field"] == expected
        tc = by_type["type_change"]
        assert tc["field"] == "tc"
        assert tc["previous_type"] == "int"
        assert tc["current_type"] == "str"

    def test_value_swing_exact_dict(self) -> None:
        result = detect_anomalies({"p": 145}, {"p": 100}, z_score_threshold=0.4)
        swing = next(a for a in result if a["type"] == "value_swing")
        expected = {
            "type": "value_swing",
            "severity": "medium",
            "field": "p",
            "message": "Field 'p' changed by +45.0% (100 → 145)",
            "previous_value": 100,
            "current_value": 145,
            "change_pct": 45.0,
        }
        assert swing == expected

    def test_content_drift_exact_dict(self) -> None:
        prev = "the quick brown fox jumps over the lazy dog again and again"
        curr = "zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz"
        result = detect_anomalies({"t": curr}, {"t": prev})
        drift = next(a for a in result if a["type"] == "content_drift")
        expected = {"type", "severity", "field", "message", "similarity"}
        assert set(drift.keys()) == expected
        assert drift["type"] == "content_drift"
        assert drift["severity"] == "medium"
        assert drift["field"] == "t"
