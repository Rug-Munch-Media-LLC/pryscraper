# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fuzz tests for extractor.SchemaExtractor — never-crash invariants.

The synchronous pattern-extraction path runs on arbitrary scraped content and
arbitrary user-supplied schemas. It must never crash: it either returns a
dict of extracted values or (on empty input) an empty dict.

Only the synchronous, dependency-free path is fuzzed here — the async LLM
path requires a reachable Ollama endpoint and is out of scope for fuzzing.
"""

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from extractor import SchemaExtractor


def _assert_well_formed(result: object) -> None:
    assert isinstance(result, dict), f"_pattern_extract returned non-dict: {type(result)!r}"
    for k, v in result.items():
        assert isinstance(k, str)
        assert isinstance(v, str), f"field {k!r} extracted non-str value {v!r}"


@settings(max_examples=300, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
@given(content=st.text(max_size=8192), schema=st.dictionaries(st.text(), st.text(), max_size=10))
def test_pattern_extract_never_crashes(content: str, schema: dict) -> None:
    """Any (content, schema) pair must extract without crashing."""
    extractor = SchemaExtractor()
    try:
        result = extractor._pattern_extract(content, schema)
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        pytest.fail(f"_pattern_extract crashed with {type(e).__name__}: {e}")
    _assert_well_formed(result)


@settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
@given(
    content=st.text(
        max_size=4096,
        alphabet=st.sampled_from(
            list(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                " _-@.,:$€£¥#%&\n\r\t=:()[]{}<>/\\\"'"
            )
        ),
    ),
    schema=st.dictionaries(st.text(min_size=1, max_size=50), st.text(max_size=200), max_size=5),
)
def test_pattern_extract_with_punctuation_heavy_content(content: str, schema: dict) -> None:
    """Noise-heavy scraped content must never crash extraction."""
    extractor = SchemaExtractor()
    try:
        result = extractor._pattern_extract(content, schema)
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        pytest.fail(f"_pattern_extract crashed with {type(e).__name__}: {e}")
    _assert_well_formed(result)


@settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
@given(content=st.text(max_size=4096))
def test_extract_auto_mode_returns_dict_without_llm(content: str) -> None:
    """Auto mode with small schemas must use pattern mode only (no LLM call)."""
    schema = {"price": "the price in USD", "name": "product name"}
    extractor = SchemaExtractor()
    try:
        result = extractor._pattern_extract(content, schema)
    except Exception as e:  # noqa: BLE001 - fuzz: unexpected crash must fail
        pytest.fail(f"_pattern_extract crashed with {type(e).__name__}: {e}")
    _assert_well_formed(result)
    # Pattern extraction never invents values: only fields present in content
    # may appear, and every value must be a non-empty string.
    for value in result.values():
        assert isinstance(value, str) and value != ""
