# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""JSON parsing / schema coercion coverage."""

from __future__ import annotations

from pry.intelligence.llm.base import coerce_to_schema, parse_json_response, strip_fences


def test_strip_fences() -> None:
    assert strip_fences('{"a": 1}') == '{"a": 1}'
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('\n\n  {"a": 1}  \n\n') == '{"a": 1}'


def test_parse_json_response_fenced_with_schema() -> None:
    schema = {"score": "int", "ok": "bool"}
    data = parse_json_response('```json\n{"score": "42", "ok": "true"}\n```', schema)
    assert data["score"] == 42
    assert data["ok"] is True


def test_parse_json_response_fallback_on_garbage() -> None:
    fallback = {"score": 0}
    data = parse_json_response("sorry, no json here", fallback=fallback)
    assert data == {"score": 0}
    # The caller's fallback dict must not be mutated by later calls.
    fallback["extra"] = True
    assert "extra" not in parse_json_response("nope", fallback={"score": 0})


def test_parse_json_response_fallback_on_non_object() -> None:
    assert parse_json_response("[1,2,3]", fallback={"x": 1}) == {"x": 1}


def test_coerce_to_schema_types_and_enums() -> None:
    schema = {
        "score": "int",
        "ratio": "float",
        "ok": "bool",
        "risk": "green|yellow|red",
        "nested": {"sub": "float"},
        "tags": {"type": "list"},
        "missing": "str",
    }
    data = coerce_to_schema(
        {
            "score": "87",
            "ratio": "0.5",
            "ok": "yes",
            "risk": "GREEN",
            "nested": {"sub": "2.5"},
            "tags": ["a", "b"],
            "unknown_key": "kept",
        },
        schema,
    )
    assert data["score"] == 87
    assert data["ratio"] == 0.5
    assert data["ok"] is True
    assert data["risk"] == "GREEN"
    assert data["nested"] == {"sub": 2.5}
    assert data["tags"] == ["a", "b"]
    assert data["missing"] is None
    assert data["unknown_key"] == "kept"


def test_coerce_to_schema_never_crashes_on_uncoercible() -> None:
    data = coerce_to_schema({"score": {"oops": 1}}, {"score": "int"})
    assert data["score"] == {"oops": 1}
