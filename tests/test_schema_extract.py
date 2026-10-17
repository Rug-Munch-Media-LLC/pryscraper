# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for pry.engine.schema_extract — schema normalization, JSON-LD/meta
lookups, confidence scoring, schema inference, and the async extraction
entry points (with _fetch_page monkeypatched). No live network.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pry.engine import schema_extract as se


class TestNormalizeSchema:
    def test_flat_form(self) -> None:
        expected = {"price": "the price"}
        assert se._normalize_schema({"price": "the price"}) == expected

    def test_structured_fields_form(self) -> None:
        schema = {
            "fields": [
                {"name": "price", "description": "the price"},
                {"name": "title"},
            ]
        }
        expected = {"price": "the price", "title": "title"}
        assert se._normalize_schema(schema) == expected

    def test_structured_skips_nameless(self) -> None:
        schema = {"fields": [{"description": "no name"}, {"name": "ok"}]}
        expected = {"ok": "ok"}
        assert se._normalize_schema(schema) == expected

    def test_non_dict_returns_empty(self) -> None:
        assert se._normalize_schema(None) == {}
        assert se._normalize_schema("nope") == {}  # type: ignore[arg-type]

    def test_flat_form_excludes_fields_key(self) -> None:
        expected = {"a": "1"}
        assert se._normalize_schema({"a": "1", "fields": "notalist"}) == expected


class TestJsonLdLookup:
    def test_direct_field(self) -> None:
        assert se._jsonld_lookup({"price": 9.99}, "price") == 9.99

    def test_name_alias_headline(self) -> None:
        assert se._jsonld_lookup({"headline": "H"}, "name") == "H"

    def test_price_alias_lowprice(self) -> None:
        assert se._jsonld_lookup({"lowPrice": 5}, "price") == 5

    def test_nested_dict_under_field_key(self) -> None:
        # The dict-unwrap branch fires when the field's own key holds a dict.
        assert se._jsonld_lookup({"price": {"price": 3.5}}, "price") == 3.5

    def test_offers_dict_not_unwrapped(self) -> None:
        # "offers" is not an alias for "price", so it is never inspected.
        assert se._jsonld_lookup({"offers": {"price": 3.5}}, "price") is None

    def test_list_takes_first(self) -> None:
        assert se._jsonld_lookup({"image": ["a.png", "b.png"]}, "image") == "a.png"

    def test_empty_list_returns_none(self) -> None:
        assert se._jsonld_lookup({"image": []}, "image") is None

    def test_missing_returns_none(self) -> None:
        assert se._jsonld_lookup({}, "price") is None

    def test_empty_string_returns_none(self) -> None:
        assert se._jsonld_lookup({"price": ""}, "price") is None

    def test_unknown_field_uses_literal_key(self) -> None:
        assert se._jsonld_lookup({"custom": "v"}, "custom") == "v"


class TestMetaTags:
    def test_name_and_property(self) -> None:
        html = '<meta name="description" content="Desc"><meta property="og:title" content="OG">'
        expected = {"description": "Desc", "og:title": "OG"}
        assert se._meta_tags(html) == expected

    def test_keys_lowercased(self) -> None:
        html = '<meta name="Description" content="D">'
        expected = {"description": "D"}
        assert se._meta_tags(html) == expected

    def test_empty_content_skipped(self) -> None:
        html = '<meta name="x" content="">'
        assert se._meta_tags(html) == {}

    def test_first_key_wins(self) -> None:
        html = '<meta name="x" content="first"><meta name="x" content="second">'
        expected = {"x": "first"}
        assert se._meta_tags(html) == expected

    def test_no_meta_returns_empty(self) -> None:
        assert se._meta_tags("<p>none</p>") == {}


class TestConfidence:
    def test_empty_schema_zero(self) -> None:
        assert se._confidence({"a": 1}, {}, "pattern") == 0.0

    def test_pattern_full(self) -> None:
        assert se._confidence({"a": 1, "b": 2}, {"a": "", "b": ""}, "pattern") == 1.0

    def test_pattern_half(self) -> None:
        assert se._confidence({"a": 1}, {"a": "", "b": ""}, "pattern") == 0.5

    def test_ai_discounts(self) -> None:
        assert se._confidence({"a": 1, "b": 2}, {"a": "", "b": ""}, "ai") == 0.85

    def test_hybrid_full(self) -> None:
        assert se._confidence({"a": 1}, {"a": ""}, "hybrid") == 1.0

    def test_empty_values_not_counted(self) -> None:
        assert se._confidence({"a": ""}, {"a": ""}, "pattern") == 0.0


class TestInferSchemaFromExample:
    def test_types(self) -> None:
        result = se.infer_schema_from_example(
            {"name": "W", "price": 9.99, "active": True, "tags": ["a"], "meta": {"x": 1}}
        )
        props = result["properties"]
        expected = {"type": "string"}
        assert props["name"] == expected
        expected_2 = {"type": "number"}
        assert props["price"] == expected_2
        expected_3 = {"type": "boolean"}
        assert props["active"] == expected_3
        expected_4 = {"type": "array"}
        assert props["tags"] == expected_4
        expected_5 = {"type": "object"}
        assert props["meta"] == expected_5

    def test_description_underscores_to_spaces(self) -> None:
        result = se.infer_schema_from_example({"product_name": "W"})
        assert result["fields"][0]["description"] == "the product name"

    def test_non_dict_returns_empty(self) -> None:
        assert se.infer_schema_from_example("nope") == {}  # type: ignore[arg-type]

    def test_empty_dict(self) -> None:
        expected = {
            "type": "object",
            "properties": {},
            "fields": [],
        }
        assert se.infer_schema_from_example({}) == expected


class TestExtractBySchema:
    @pytest.mark.asyncio
    async def test_invalid_inputs_return_empty(self) -> None:
        assert await se.extract_by_schema("", {"a": "b"}) == {}
        assert await se.extract_by_schema("http://x", "notadict") == {}  # type: ignore[arg-type]
        assert await se.extract_by_schema("http://x", {}) == {}

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_none_method(self) -> None:
        with patch.object(
            se, "_fetch_page", new=AsyncMock(return_value={"html": "", "content": "", "method": ""})
        ):
            result = await se.extract_by_schema("http://x", {"title": "t"})
        expected = {"url": "http://x", "data": {}, "method": "none", "confidence": 0.0}
        assert result == expected

    @pytest.mark.asyncio
    async def test_meta_tag_extraction(self) -> None:
        html = '<meta name="title" content="From Meta">'
        with patch.object(
            se,
            "_fetch_page",
            new=AsyncMock(return_value={"html": html, "content": "", "method": "http"}),
        ):
            result = await se.extract_by_schema("http://x", {"title": "t"}, use_ai=False)
        expected = {"title": "From Meta"}
        assert result["data"] == expected
        assert result["method"] == "pattern"
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_ai_fallback_hybrid(self) -> None:
        html = '<meta name="title" content="From Meta">'
        ai = AsyncMock(return_value={"price": "9.99", "_error": "x", "_raw": "y"})
        with (
            patch.object(
                se,
                "_fetch_page",
                new=AsyncMock(return_value={"html": html, "content": "body", "method": "http"}),
            ),
            patch("pry.engine.extractor.SchemaExtractor") as extractor_cls,
        ):
            extractor_cls.return_value.extract = ai
            result = await se.extract_by_schema(
                "http://x", {"title": "t", "price": "p"}, use_ai=True
            )
        expected = {"title": "From Meta", "price": "9.99"}
        assert result["data"] == expected
        assert result["method"] == "hybrid"
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_ai_only_when_no_pattern_data(self) -> None:
        ai = AsyncMock(return_value={"price": "9.99"})
        with (
            patch.object(
                se,
                "_fetch_page",
                new=AsyncMock(return_value={"html": "", "content": "body", "method": "http"}),
            ),
            patch("pry.engine.extractor.SchemaExtractor") as extractor_cls,
        ):
            extractor_cls.return_value.extract = ai
            result = await se.extract_by_schema("http://x", {"price": "p"}, use_ai=True)
        expected = {"price": "9.99"}
        assert result["data"] == expected
        assert result["method"] == "ai"
        assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_ai_exception_never_raises(self) -> None:
        with (
            patch.object(
                se,
                "_fetch_page",
                new=AsyncMock(return_value={"html": "", "content": "body", "method": "http"}),
            ),
            patch("pry.engine.extractor.SchemaExtractor", side_effect=RuntimeError("boom")),
        ):
            result = await se.extract_by_schema("http://x", {"price": "p"}, use_ai=True)
        assert result["data"] == {}
        assert result["method"] == "none"


class TestExtractBatchBySchema:
    @pytest.mark.asyncio
    async def test_invalid_inputs_return_empty_list(self) -> None:
        assert await se.extract_batch_by_schema("notalist", {"a": "b"}) == []  # type: ignore[arg-type]
        assert await se.extract_batch_by_schema(["u"], "notadict") == []  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_preserves_input_order(self) -> None:
        async def fake(url: str, schema: dict, use_ai: bool = True) -> dict:
            return {"url": url, "data": {}, "method": "none", "confidence": 0.0}

        with patch.object(se, "extract_by_schema", side_effect=fake):
            results = await se.extract_batch_by_schema(["a", "b", "c"], {"x": "y"})
        expected = ["a", "b", "c"]
        assert [r["url"] for r in results] == expected


class TestExtractWithPrompt:
    @pytest.mark.asyncio
    async def test_invalid_inputs_return_empty(self) -> None:
        assert await se.extract_with_prompt("", "prompt") == {}
        assert await se.extract_with_prompt("http://x", "") == {}

    @pytest.mark.asyncio
    async def test_no_content_returns_none_method(self) -> None:
        with patch.object(
            se, "_fetch_page", new=AsyncMock(return_value={"html": "", "content": "", "method": ""})
        ):
            result = await se.extract_with_prompt("http://x", "get price")
        expected = {"url": "http://x", "data": {}, "method": "none", "confidence": 0.0}
        assert result == expected

    @pytest.mark.asyncio
    async def test_llm_result_filtered(self) -> None:
        ai = AsyncMock(return_value={"price": "9.99", "empty": "", "_error": "e", "_raw": "r"})
        with (
            patch.object(
                se,
                "_fetch_page",
                new=AsyncMock(return_value={"html": "", "content": "body", "method": "http"}),
            ),
            patch("pry.engine.extractor.SchemaExtractor") as extractor_cls,
        ):
            extractor_cls.return_value.extract = ai
            result = await se.extract_with_prompt("http://x", "get price", {"price": "p"})
        expected = {"price": "9.99"}
        assert result["data"] == expected
        assert result["method"] == "ai"

    @pytest.mark.asyncio
    async def test_llm_exception_never_raises(self) -> None:
        with (
            patch.object(
                se,
                "_fetch_page",
                new=AsyncMock(return_value={"html": "", "content": "body", "method": "http"}),
            ),
            patch("pry.engine.extractor.SchemaExtractor", side_effect=RuntimeError("boom")),
        ):
            result = await se.extract_with_prompt("http://x", "get price")
        assert result["data"] == {}
        assert result["method"] == "none"


class TestExtractTable:
    @pytest.mark.asyncio
    async def test_empty_url_returns_empty(self) -> None:
        assert await se.extract_table("") == []

    @pytest.mark.asyncio
    async def test_no_html_returns_empty(self) -> None:
        with patch.object(
            se, "_fetch_page", new=AsyncMock(return_value={"html": "", "content": "", "method": ""})
        ):
            assert await se.extract_table("http://x") == []

    @pytest.mark.asyncio
    async def test_parses_table(self) -> None:
        html = (
            "<table><tr><th>Name</th><th>Price</th></tr>"
            "<tr><td>Widget</td><td>9.99</td></tr></table>"
        )
        with patch.object(
            se,
            "_fetch_page",
            new=AsyncMock(return_value={"html": html, "content": "", "method": "http"}),
        ):
            rows = await se.extract_table("http://x")
        expected = [{"Name": "Widget", "Price": "9.99"}]
        assert rows == expected

    @pytest.mark.asyncio
    async def test_no_table_returns_empty(self) -> None:
        with patch.object(
            se,
            "_fetch_page",
            new=AsyncMock(
                return_value={"html": "<p>no table</p>", "content": "", "method": "http"}
            ),
        ):
            assert await se.extract_table("http://x") == []

    @pytest.mark.asyncio
    async def test_missing_header_gets_col_fallback(self) -> None:
        html = "<table><tr><th>A</th></tr><tr><td>1</td><td>2</td></tr></table>"
        with patch.object(
            se,
            "_fetch_page",
            new=AsyncMock(return_value={"html": html, "content": "", "method": "http"}),
        ):
            rows = await se.extract_table("http://x")
        expected = [{"A": "1", "col_1": "2"}]
        assert rows == expected
