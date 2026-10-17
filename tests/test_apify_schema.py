# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT.
"""Tests for the Apify schema builder."""

from pry.actors.apify_schema import ApifySchemaBuilder


def test_input_schema_basic() -> None:
    schema = (
        ApifySchemaBuilder("Product Scraper", "Scrape product details")
        .add_string("url", "Start URL", description="The URL to scrape", required=True)
        .add_integer("maxResults", "Max Results", default=10, minimum=1, maximum=100)
        .add_enum("format", "Output Format", ["json", "csv", "markdown"], default="json")
        .build_input_schema()
    )

    assert schema["title"] == "Product Scraper"
    assert schema["description"] == "Scrape product details"
    assert schema["type"] == "object"
    assert schema["schemaVersion"] == 1
    expected = ["url"]
    assert schema["required"] == expected
    assert schema["properties"]["url"]["type"] == "string"
    assert schema["properties"]["maxResults"]["default"] == 10
    expected_2 = ["json", "csv", "markdown"]
    assert schema["properties"]["format"]["enum"] == expected_2


def test_output_schema_includes_required() -> None:
    schema = (
        ApifySchemaBuilder("Product Output")
        .add_string("title", "Title", required=True)
        .add_number("price", "Price", minimum=0)
        .add_boolean("inStock", "In Stock", default=True)
        .build_output_schema()
    )

    assert schema["properties"]["title"]["type"] == "string"
    assert schema["properties"]["price"]["minimum"] == 0
    assert schema["properties"]["inStock"]["default"] is True
    expected = ["title"]
    assert schema["required"] == expected


def test_array_and_object_fields() -> None:
    schema = (
        ApifySchemaBuilder("Complex Actor")
        .add_array("urls", "URLs", {"type": "string"}, required=True, min_items=1, max_items=50)
        .add_object(
            "proxy",
            "Proxy Config",
            {"host": {"type": "string"}, "port": {"type": "integer"}},
            nested_required=["host"],
        )
        .build_input_schema()
    )

    assert schema["properties"]["urls"]["type"] == "array"
    assert schema["properties"]["urls"]["minItems"] == 1
    assert schema["properties"]["urls"]["items"]["type"] == "string"
    assert schema["properties"]["proxy"]["type"] == "object"
    expected = ["host"]
    assert schema["properties"]["proxy"]["required"] == expected


def test_nullable_field() -> None:
    schema = (
        ApifySchemaBuilder().add_string("optional", "Optional", nullable=True).build_input_schema()
    )
    expected = ["string", "null"]
    assert schema["properties"]["optional"]["type"] == expected


def test_prefab() -> None:
    schema = (
        ApifySchemaBuilder()
        .set_prefab("START_URLS")
        .add_string("url", "URL", required=True)
        .build_input_schema()
    )
    assert schema["prefab"] == "START_URLS"
