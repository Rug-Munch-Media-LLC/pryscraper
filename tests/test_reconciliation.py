# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for entity reconciliation."""

from pry.commerce.reconciliation import (
    VERTICAL_SCHEMAS,
    _build_field_map,
    _normalize_record,
    compute_similarity,
    match_entities,
)


def test_compute_similarity_exact() -> None:
    assert compute_similarity("iPhone 15", "iPhone 15") == 1.0


def test_compute_similarity_partial() -> None:
    sim = compute_similarity("iPhone 15 Pro Max", "iPhone 15 Pro")
    assert sim > 0.5


def test_compute_similarity_different() -> None:
    sim = compute_similarity("iPhone 15", "Samsung Galaxy S24")
    assert sim < 0.5


def test_compute_similarity_empty() -> None:
    assert compute_similarity("", "test") == 0.0
    assert compute_similarity("test", "") == 0.0


def test_match_entities_products() -> None:
    records = [
        {
            "name": "iPhone 15 Pro",
            "price": 999,
            "url": "https://amazon.com/iphone",
            "_source": "amazon",
        },
        {
            "name": "iPhone 15 Pro",
            "price": 999.99,
            "url": "https://walmart.com/iphone",
            "_source": "walmart",
        },
        {"name": "Samsung TV", "price": 499, "url": "https://bestbuy.com/tv", "_source": "bestbuy"},
    ]
    entities = match_entities(records, "product", threshold=0.7)
    assert len(entities) >= 2
    iphone_entity = [e for e in entities if "iphone" in str(e).lower()]
    assert len(iphone_entity) > 0
    assert iphone_entity[0]["record_count"] >= 2


def test_build_field_map() -> None:
    schema = VERTICAL_SCHEMAS["product"]
    field_map = _build_field_map(schema)
    assert field_map["name"] == "name"
    assert field_map["title"] == "name"
    assert field_map["cost"] == "price"


def test_normalize_record() -> None:
    schema = VERTICAL_SCHEMAS["product"]
    field_map = _build_field_map(schema)
    record = {"title": "iPhone", "cost": "$999.99", "link": "https://example.com"}
    normalized = _normalize_record(record, field_map, schema)
    assert normalized.get("name") == "iPhone"
    assert normalized.get("price") == 999.99
    assert normalized.get("url") == "https://example.com"


def test_list_schemas_keys() -> None:
    assert "product" in VERTICAL_SCHEMAS
    assert "job" in VERTICAL_SCHEMAS
    assert "real_estate" in VERTICAL_SCHEMAS
    assert "review" in VERTICAL_SCHEMAS


def test_identity_fields_present() -> None:
    for _key, schema in VERTICAL_SCHEMAS.items():
        assert len(schema["identity_fields"]) > 0
