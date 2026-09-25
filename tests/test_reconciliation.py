# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Deterministic characterization tests for entity reconciliation."""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from pry.commerce import reconciliation as legacy
from pry.commerce.reconciliation import (
    VERTICAL_SCHEMAS,
    _build_field_map,
    _convert_type,
    _normalize_record,
    build_reconciliation_report,
    compute_similarity,
    match_entities,
)

try:
    from pry.commerce.reconciliation import matching as new_matching, reporting as new_reporting
except ImportError:
    new_matching = new_reporting = None


def _row(source: str, **fields: object) -> dict[str, object]:
    return {"_source": source, **fields}


VERTICAL_CASES = {
    "product": [
        _row("a", title="Widget", cost="$12.5", link="u1"),
        _row("b", name="Widget", price=12.5, url="u1"),
        _row("c", title="Other", cost="$8", link="u2"),
    ],
    "job": [
        _row("a", title="Engineer", company="Acme", url="j1"),
        _row("b", title="Engineer", company="Acme", url="j2"),
        _row("c", title="Designer", company="Other", url="j3"),
    ],
    "real_estate": [
        _row("a", location="1 Main St", listing_price="$500", link="h1"),
        _row("b", address="1 Main St", price=500, url="h2"),
        _row("c", location="999 Remote Road", listing_price="$600", link="h3"),
    ],
    "review": [
        _row("a", product_name="Widget", author="Lee", title="Great", url="r1"),
        _row("b", product_name="Widget", author="Lee", title="Great", url="r2"),
        _row("c", product_name="Other", author="Lee", title="Bad", url="r3"),
    ],
}
NORMALIZATION_CASES = [
    (
        "product",
        {"title": "P", "cost": "$1234.50", "link": "u", "id": "s"},
        {"name": "P", "price": 1234.5, "url": "u", "sku": "s"},
    ),
    (
        "job",
        {"title": "J", "company": "C", "salary_min": "$120000", "summary": "S"},
        {"title": "J", "company": "C", "salary_min": 120000.0, "description": "S"},
    ),
    (
        "real_estate",
        {"full_address": "A", "amount": "$10.5", "bedrooms": "2"},
        {"address": "A", "price": 10.5, "bedrooms": 2},
    ),
    (
        "review",
        {"product_name": "R", "stars": "5", "source": "reviews"},
        {"product_name": "R", "rating": 5, "_source": "reviews"},
    ),
]


class TestReconciliation:
    @pytest.mark.parametrize("vertical", VERTICAL_CASES)
    def test_every_vertical_matches_alias_equivalent_records(self, vertical: str) -> None:
        assert set(VERTICAL_CASES) == set(VERTICAL_SCHEMAS)
        entities = match_entities(VERTICAL_CASES[vertical], vertical)
        assert sorted(entity["record_count"] for entity in entities) == [1, 2]
        assert {source for entity in entities for source in entity["sources"]} == {"a", "b", "c"}
        assert all(0.0 <= entity["confidence"] <= 1.0 for entity in entities)

    @pytest.mark.parametrize(("vertical", "raw", "expected"), NORMALIZATION_CASES)
    def test_alias_normalization_and_type_conversion(
        self, vertical: str, raw: dict[str, object], expected: dict[str, object]
    ) -> None:
        schema = VERTICAL_SCHEMAS[vertical]
        normalized = _normalize_record(raw, _build_field_map(schema), schema)
        assert all(normalized[field] == value for field, value in expected.items())
        assert normalized["_raw"] == raw

    @pytest.mark.parametrize(
        ("value", "target", "expected"),
        [
            ("$1234.50", "float", 1234.5),
            ("$12", "int", 12),
            ("in stock", "bool", True),
            (" in stock ", "bool", False),
            ("1,234.50", "float", None),
            (None, "int", None),
        ],
    )
    def test_type_conversion_boundaries(self, value: object, target: str, expected: object) -> None:
        assert _convert_type(value, target) == expected

    def test_similarity_threshold_is_inclusive(self) -> None:
        records = [{"name": "Acme Widget"}, {"name": "Acme Widget Pro"}]
        assert compute_similarity(records[0]["name"], records[1]["name"]) == pytest.approx(2 / 3)
        assert compute_similarity("", "Acme") == 0.0
        assert len(match_entities(records, "product", threshold=0.6)) == 1
        assert len(match_entities(records, "product", threshold=0.7)) == 2

    @given(threshold=st.floats(min_value=0.0, max_value=1.0))
    @settings(max_examples=40, derandomize=True, deadline=None)
    def test_exact_identity_meets_every_threshold(self, threshold: float) -> None:
        records = [
            {"name": "Same", "sku": "S", "url": "u"},
            {"name": "Same", "sku": "S", "url": "u"},
        ]
        assert len(match_entities(records, "product", threshold)) == 1

    @given(label=st.text(min_size=1, max_size=30), code=st.text(min_size=1, max_size=30))
    @settings(max_examples=40, derandomize=True, deadline=None)
    def test_alias_equivalence_preserves_entity_id(self, label: str, code: str) -> None:
        canonical = {"name": label, "sku": code, "url": "u"}
        alias = {"title": label, "product_id": code, "link": "u"}
        assert (
            match_entities([canonical], "product")[0]["entity_id"]
            == match_entities([alias], "product")[0]["entity_id"]
        )

    def test_ids_order_and_confidence_are_stable(self) -> None:
        records = [
            {"name": "B", "_source": "b"},
            {"name": "A", "_source": "a"},
            {"name": "B", "_source": "c"},
            {"name": "Same", "_source": "d"},
            {"name": "Same", "_source": "e"},
        ]
        first = match_entities(records, "product")
        second = match_entities(records, "product")
        assert [(e["entity_id"], e["records"][0]["name"]) for e in first] == [
            (e["entity_id"], e["records"][0]["name"]) for e in second
        ]
        assert [e["records"][0]["name"] for e in first] == ["B", "A", "Same"]
        assert [e["confidence"] for e in first] == [1.0, 0.5, 1.0]

    def test_report_rates_counts_confidence_and_sources(self) -> None:
        entities = [
            {"record_count": 2, "confidence": 0.9, "sources": ["a", "b"]},
            {"record_count": 1, "confidence": 0.5, "sources": ["c"]},
            {"record_count": 1, "confidence": 0.4, "sources": []},
        ]
        report = build_reconciliation_report(entities, "product")
        assert (report["total_records"], report["total_entities"], report["match_rate"]) == (
            4,
            3,
            33.3,
        )
        assert (report["matched_entities"], report["unmatched_records"]) == (1, 2)
        assert (report["high_confidence"], report["low_confidence"]) == (1, 1)
        assert set(report["unique_sources"]) == {"a", "b", "c"}

    def test_malformed_entities_are_contained(self) -> None:
        records: list[dict[str, object]] = [
            {"name": None},
            {"name": ["bad"]},
            {"unknown": {"x": 1}},
        ]
        entities = match_entities(records, "product")
        assert len(entities) == 3
        assert all(
            entity["confidence"] == 0.5 and len(entity["entity_id"]) == 12 for entity in entities
        )

    def test_unknown_vertical_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown vertical: unknown"):
            match_entities([], "unknown")

    @pytest.mark.parametrize("vertical", VERTICAL_CASES)
    def test_legacy_and_new_module_parity(self, vertical: str) -> None:
        if new_matching is None or new_reporting is None:
            pytest.skip("new reconciliation modules are not present")
        records = VERTICAL_CASES[vertical]
        old = legacy.match_entities(records, vertical)
        assert old == new_matching.match_entities(records, vertical)
        assert legacy.build_reconciliation_report(
            old, vertical
        ) == new_reporting.build_reconciliation_report(old, vertical)
