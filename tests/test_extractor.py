# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import pytest

from extractor import SchemaExtractor


@pytest.fixture
def extractor() -> SchemaExtractor:
    return SchemaExtractor()


@pytest.mark.asyncio
async def test_extract_pattern_mode(extractor: SchemaExtractor, sample_markdown: str) -> None:
    schema = {"price": "price in USD", "email": "contact email"}
    result = await extractor.extract(sample_markdown, schema, mode="pattern")
    assert "price" in result
    assert result["price"] is not None
    assert "email" in result


@pytest.mark.asyncio
async def test_extract_empty_content(extractor: SchemaExtractor) -> None:
    result = await extractor.extract("", {"name": "product name"})
    assert result == {}


@pytest.mark.asyncio
async def test_extract_empty_schema(extractor: SchemaExtractor, sample_markdown: str) -> None:
    result = await extractor.extract(sample_markdown, {})
    assert result == {}


def test_pattern_extract_email(extractor: SchemaExtractor) -> None:
    content = "Contact us at support@example.com or call 555-0100"
    result = extractor._pattern_extract(content, {"email": "email address"})
    assert "email" in result
    assert "@" in result["email"]


def test_pattern_extract_price(extractor: SchemaExtractor) -> None:
    content = "Price: $49.99 USD"
    result = extractor._pattern_extract(content, {"price": "price in usd"})
    assert "price" in result
    assert "$" in result["price"] or "USD" in result["price"]


def test_pattern_extract_url(extractor: SchemaExtractor) -> None:
    content = "Visit https://example.com/page for details"
    result = extractor._pattern_extract(content, {"url": "website link"})
    assert "url" in result
    assert result["url"].startswith("http")


def test_pattern_extract_labeled_value(extractor: SchemaExtractor) -> None:
    content = "product_name: SuperWidget\nprice: $19.99"
    result = extractor._pattern_extract(content, {"product_name": "name"})
    assert result.get("product_name") == "SuperWidget"
