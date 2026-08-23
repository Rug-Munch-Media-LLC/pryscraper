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

import time

import pytest

from quality import (
    _format_age,
    compute_completeness,
    compute_freshness,
    compute_null_rate,
    compute_schema_adherence,
    detect_anomalies,
)

# ── detect_anomalies ─────────────────────────────────────────────────────────


class TestDetectAnomaliesContract:
    def test_no_previous_data_means_no_anomalies(self) -> None:
        assert detect_anomalies({"a": 1}, None) == []

    def test_empty_current_with_previous_is_critical(self) -> None:
        result = detect_anomalies({}, {"a": 1})
        assert result == [
            {
                "type": "empty_result",
                "severity": "critical",
                "field": "*",
                "message": "Extraction returned empty — previous run had data",
            }
        ]

    def test_non_dict_inputs_return_empty(self) -> None:
        assert detect_anomalies(["x"], {"a": 1}) == []  # type: ignore[arg-type]
        assert detect_anomalies({"a": 1}, ["x"]) == []  # type: ignore[arg-type]

    def test_missing_field_high(self) -> None:
        result = detect_anomalies({"b": 2}, {"a": 1, "b": 2})
        missing = [a for a in result if a["type"] == "missing_field"]
        assert len(missing) == 1
        assert missing[0]["severity"] == "high"
        assert missing[0]["field"] == "a"

    def test_new_field_info(self) -> None:
        result = detect_anomalies({"a": 1, "new": 9}, {"a": 1})
        new = [a for a in result if a["type"] == "new_field"]
        assert new == [
            {
                "type": "new_field",
                "severity": "info",
                "field": "new",
                "message": "New field 'new' appeared",
            }
        ]

    def test_type_change_high_and_none_values_exempt(self) -> None:
        result = detect_anomalies({"a": "now-str"}, {"a": 42})
        tc = [a for a in result if a["type"] == "type_change"]
        assert len(tc) == 1
        assert tc[0]["severity"] == "high"
        assert tc[0]["previous_type"] == "int"
        assert tc[0]["current_type"] == "str"
        # None on either side never counts as a type change.
        assert [
            a for a in detect_anomalies({"a": None}, {"a": 42}) if a["type"] == "type_change"
        ] == []
        assert [
            a for a in detect_anomalies({"a": 1}, {"a": None}) if a["type"] == "type_change"
        ] == []


class TestValueSwingBoundaries:
    """z = |curr-prev| / max(|prev|, 0.01); flag iff z > threshold."""

    def test_swing_at_exactly_threshold_not_flagged(self) -> None:
        # prev=100, curr=300 -> z = 200/100 = 2.0 == threshold -> NO anomaly.
        result = detect_anomalies({"p": 300}, {"p": 100}, z_score_threshold=2.0)
        assert [a for a in result if a["type"] == "value_swing"] == []

    def test_swing_just_over_threshold_flagged_medium(self) -> None:
        # prev=1000, curr=1001 -> z ~= 0.001... use clear numbers instead:
        # prev=100, curr=301 -> z = 2.01 > 2.0; pct = 201% -> high (>50).
        result = detect_anomalies({"p": 301}, {"p": 100}, z_score_threshold=2.0)
        swings = [a for a in result if a["type"] == "value_swing"]
        assert len(swings) == 1
        assert swings[0]["severity"] == "high"

    def test_small_numeric_change_stays_medium(self) -> None:
        # prev=100, curr=130 -> z=0.3 < 2 -> nothing. For medium we need
        # z>threshold but |pct| <= 50: prev=-200? abs() handles sign.
        # prev=100, curr=145, threshold=1.2 -> z=0.45 < 1.2 no...
        # Use prev=40, curr=59: z=19/40=0.475. Simpler: threshold tiny.
        result = detect_anomalies({"p": 145}, {"p": 100}, z_score_threshold=0.4)
        swings = [a for a in result if a["type"] == "value_swing"]
        assert len(swings) == 1
        assert swings[0]["severity"] == "medium"  # pct=45 <= 50
        assert swings[0]["change_pct"] == 45.0

    def test_severity_high_only_above_50_pct(self) -> None:
        at_50 = detect_anomalies({"p": 150}, {"p": 100}, z_score_threshold=0.4)
        over_50 = detect_anomalies({"p": 151}, {"p": 100}, z_score_threshold=0.4)
        assert at_50[0]["severity"] == "medium"  # pct == 50 exactly
        assert over_50[0]["severity"] == "high"  # pct == 51

    def test_zero_previous_value_never_swings(self) -> None:
        result = detect_anomalies({"p": 999999}, {"p": 0}, z_score_threshold=0.001)
        assert [a for a in result if a["type"] == "value_swing"] == []


class TestContentDriftBoundaries:
    def test_short_previous_text_never_drifts(self) -> None:
        # len(prev) == 20 is NOT eligible (strictly > 20 required).
        prev = "x" * 20
        result = detect_anomalies({"t": "completely different!!"}, {"t": prev})
        assert [a for a in result if a["type"] == "content_drift"] == []

    def test_long_dissimilar_text_drifts_medium(self) -> None:
        prev = "the quick brown fox jumps over the lazy dog again and again"
        curr = "zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz"
        result = detect_anomalies({"t": curr}, {"t": prev})
        drifts = [a for a in result if a["type"] == "content_drift"]
        assert len(drifts) == 1
        assert drifts[0]["severity"] == "medium"

    def test_similar_rewrites_do_not_drift(self) -> None:
        prev = "the quick brown fox jumps over the lazy dog again and again"
        curr = "the quick brown fox jumps over the lazy dog again and AGAIN!"
        result = detect_anomalies({"t": curr}, {"t": prev})
        assert [a for a in result if a["type"] == "content_drift"] == []


# ── compute_freshness / _format_age ─────────────────────────────────────────


class TestFormatAgeLadder:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "0s"),
            (59, "59s"),
            (60, "1m"),
            (119, "1m"),
            (3599, "59m"),
            (3600, "1h"),
            (86399, "23h"),
            (86400, "1d"),
            (90000, "1d"),
        ],
    )
    def test_exact_boundaries(self, seconds: float, expected: str) -> None:
        assert _format_age(seconds) == expected


class TestComputeFreshness:
    def test_no_timestamp_field_is_fresh_unknown(self) -> None:
        result = compute_freshness({"unrelated": 1})
        assert result == {
            "fresh": True,
            "age_seconds": None,
            "note": "No timestamp field found in data — cannot verify freshness",
        }

    def test_timestamp_key_priority_order(self) -> None:
        """'timestamp' wins even when other recognised keys also exist."""
        now = time.time()
        result = compute_freshness({"timestamp": now - 10, "checked_at": now - 99999})
        assert result["age_seconds"] == 10

    def test_epoch_int_age_and_fresh_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Freeze the clock so age is EXACTLY max_age — pins the '<=' in
        # ``age <= max_age_seconds`` against a '<' mutant.
        import quality as quality_module

        frozen = 1_800_000_000.0
        monkeypatch.setattr(quality_module.time, "time", lambda: frozen)
        result = compute_freshness({"timestamp": frozen - 3600}, max_age_seconds=3600)
        assert result["fresh"] is True  # age == max_age IS fresh
        assert result["age_seconds"] == 3600
        stale = compute_freshness({"timestamp": frozen - 3661}, max_age_seconds=3600)
        assert stale["fresh"] is False
        assert stale["age_seconds"] == 3661

    def test_iso_string_timestamp_parsed(self) -> None:
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
        result = compute_freshness({"checked_at": ts})
        assert result["fresh"] is True
        assert 25 <= (result["age_seconds"] or 0) <= 35

    def test_unparseable_string_returns_note(self) -> None:
        result = compute_freshness({"timestamp": "not-a-date-at-all"})
        assert result["fresh"] is True
        assert result["age_seconds"] is None
        assert "not-a-date-at-all" in result["note"]

    def test_unknown_type_timestamp(self) -> None:
        result = compute_freshness({"timestamp": ["nope"]})
        assert result == {
            "fresh": True,
            "age_seconds": None,
            "note": "Timestamp in unknown format",
        }


# ── completeness ─────────────────────────────────────────────────────────────


class TestDictCompleteness:
    def test_empty_dict_contract(self) -> None:
        assert compute_completeness({}) == {
            "score": 0,
            "total_fields": 0,
            "filled_fields": 0,
            "null_fields": 0,
            "empty_fields": 0,
        }

    def test_classification_filled_null_empty(self) -> None:
        data = {
            "good": "value",
            "zero": 0,  # falsy but FILLED (not in (None, "", [], {}))
            "falsey": False,  # also FILLED
            "none": None,
            "blank": "",
            "list": [],
            "obj": {},
        }
        result = compute_completeness(data)
        assert result["total_fields"] == 7
        assert result["filled_fields"] == 3
        assert result["null_fields"] == 1
        assert result["empty_fields"] == 3
        assert result["score"] == round(3 / 7 * 100, 1)

    def test_score_rounding_to_one_decimal(self) -> None:
        # 1/3 filled -> 33.333.. -> 33.3
        result = compute_completeness({"a": 1, "b": None, "c": None})
        assert result["score"] == 33.3


class TestListCompleteness:
    def test_empty_list_contract_three_keys_only(self) -> None:
        assert compute_completeness([]) == {
            "score": 0,
            "record_count": 0,
            "avg_record_score": 0,
        }

    def test_full_shape_with_records(self) -> None:
        records = [{"a": 1, "b": 2}, {"a": 1, "b": None}]
        result = compute_completeness(records)
        assert result["record_count"] == 2
        assert result["min_record_score"] == 50.0
        assert result["max_record_score"] == 100.0
        assert result["avg_record_score"] == 75.0
        # overall = filled(3) / possible(4) * 100
        assert result["score"] == 75.0

    def test_non_dict_records_counted_but_unscored(self) -> None:
        result = compute_completeness([{"a": 1}, "junk", 42])
        assert result["record_count"] == 3
        assert result["score"] == 100.0  # only the dict record contributes
        assert result["avg_record_score"] == 100.0


# ── schema adherence & null rate ────────────────────────────────────────────


class TestSchemaAdherence:
    def test_no_expected_types_scores_perfect(self) -> None:
        result = compute_schema_adherence({"a": 1}, {})
        assert result == {
            "score": 100.0,
            "total_checks": 0,
            "type_mismatches": 0,
            "field_issues": {},
        }

    def test_mismatch_tracking_per_field(self) -> None:
        data = [{"a": "str-not-int", "b": 1}, {"a": 5, "b": "also-not-int"}]
        result = compute_schema_adherence(data, {"a": int, "b": int})
        assert result["total_checks"] == 4
        assert result["type_mismatches"] == 2
        assert result["field_issues"] == {"a": 1, "b": 1}
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
        assert result["a"] == {"null_rate": 66.7, "empty_rate": 0.0, "total": 3}
        assert result["b"] == {"null_rate": 0.0, "empty_rate": 66.7, "total": 3}
        assert result["c"] == {"null_rate": 0.0, "empty_rate": 0.0, "total": 3}

    def test_single_dict_wrapped(self) -> None:
        result = compute_null_rate({"x": None})
        assert result["x"] == {"null_rate": 100.0, "empty_rate": 0.0, "total": 1}


class TestFreshnessKeyCoverage:
    """Every recognised timestamp key must be honoured (kills key-rename mutants)."""

    @pytest.mark.parametrize(
        "key", ["timestamp", "checked_at", "cached_at", "scraped_at", "created_at", "updated_at"]
    )
    def test_each_recognised_key_drives_age(
        self, monkeypatch: pytest.MonkeyPatch, key: str
    ) -> None:
        import quality as quality_module

        frozen = 1_800_000_000.0
        monkeypatch.setattr(quality_module.time, "time", lambda: frozen)
        result = compute_freshness({key: frozen - 60})
        assert result["age_seconds"] == 60
        assert result["fresh"] is True

    def test_default_max_age_is_3600(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """age = 3600.5s: fresh under default 3600? NO (<= 3600 fails).
        A 3601 default mutant would wrongly report fresh."""
        import quality as quality_module

        frozen = 1_800_000_000.0
        monkeypatch.setattr(quality_module.time, "time", lambda: frozen)
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
        assert [a["type"] for a in result if a["type"] == "value_swing"] == ["value_swing"]
        # And z = 1.5 must stay quiet at the default threshold.
        quiet = detect_anomalies({"p": 250}, {"p": 100})
        assert [a for a in quiet if a["type"] == "value_swing"] == []

    def test_missing_field_exact_dict(self) -> None:
        assert detect_anomalies({"b": 2}, {"a": 1, "b": 2}) == [
            {
                "type": "missing_field",
                "severity": "high",
                "field": "a",
                "message": ("Field 'a' was present in previous extraction but is now missing"),
            }
        ]

    def test_new_field_and_type_change_exact_dicts(self) -> None:
        result = detect_anomalies({"keep": 1, "add": 2, "tc": "s"}, {"keep": 1, "tc": 9})
        by_type = {a["type"]: a for a in result}
        assert by_type["new_field"] == {
            "type": "new_field",
            "severity": "info",
            "field": "add",
            "message": "New field 'add' appeared",
        }
        tc = by_type["type_change"]
        assert tc["field"] == "tc"
        assert tc["previous_type"] == "int"
        assert tc["current_type"] == "str"

    def test_value_swing_exact_dict(self) -> None:
        result = detect_anomalies({"p": 145}, {"p": 100}, z_score_threshold=0.4)
        swing = next(a for a in result if a["type"] == "value_swing")
        assert swing == {
            "type": "value_swing",
            "severity": "medium",
            "field": "p",
            "message": "Field 'p' changed by +45.0% (100 → 145)",
            "previous_value": 100,
            "current_value": 145,
            "change_pct": 45.0,
        }

    def test_content_drift_exact_dict(self) -> None:
        prev = "the quick brown fox jumps over the lazy dog again and again"
        curr = "zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz zz"
        result = detect_anomalies({"t": curr}, {"t": prev})
        drift = next(a for a in result if a["type"] == "content_drift")
        assert set(drift.keys()) == {"type", "severity", "field", "message", "similarity"}
        assert drift["type"] == "content_drift"
        assert drift["severity"] == "medium"
        assert drift["field"] == "t"
