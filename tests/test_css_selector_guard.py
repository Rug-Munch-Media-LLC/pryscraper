"""Tests for the CSS selector ReDoS guard.

The security audit found that ``pry_extract`` accepts user-provided CSS
selectors that are passed straight to BeautifulSoup/Parsel/lxml cssselect.
Crafted selectors can trigger catastrophic backtracking (ReDoS). These tests
pin the ``_validate_css_selector`` guard and its integration at the entry
points where user selectors enter the system.
"""

from __future__ import annotations

import asyncio

import pytest

from extraction.css import (
    JsonCssExtractionStrategy,
    _validate_css_selector,
    extract_structured,
)
from pry_mcp.tools.scraping import validate_schema_selectors

# ── valid selectors pass ──


@pytest.mark.parametrize(
    "selector",
    [
        "h1",
        ".product-card",
        "div.product-card > h3.title",
        "ul li a[href]",
        "#main .price",
        "table tr:nth-child(2) td",
        "div[data-type='a b'] span",  # spaces inside attribute values are fine
        "a[href^='https://']",
    ],
)
def test_valid_selectors_pass(selector: str) -> None:
    assert _validate_css_selector(selector) == selector


# ── overly long selectors rejected ──


def test_overly_long_selector_rejected() -> None:
    long_selector = ".a" * 300  # 600 chars > 500 limit
    with pytest.raises(ValueError, match="exceeds max length"):
        _validate_css_selector(long_selector)


def test_boundary_length_selector_accepted() -> None:
    # Exactly at the limit is allowed.
    selector = ".a" * 250  # 500 chars
    assert len(selector) == 500
    assert _validate_css_selector(selector) == selector


# ── excessive nesting rejected ──


def test_excessive_nesting_rejected() -> None:
    # 25 child combinators > 20 limit.
    nested = " > ".join(["div"] * 26)
    with pytest.raises(ValueError, match="too many combinators"):
        _validate_css_selector(nested)


def test_excessive_descendant_nesting_rejected() -> None:
    # 25 descendant combinators (spaces) > 20 limit.
    nested = " ".join(["div"] * 26)
    with pytest.raises(ValueError, match="too many combinators"):
        _validate_css_selector(nested)


def test_moderate_nesting_accepted() -> None:
    # 10 combinators is well within the limit.
    nested = " > ".join(["div"] * 11)
    assert _validate_css_selector(nested) == nested


# ── ReDoS patterns rejected ──


def test_nested_quantifier_rejected() -> None:
    with pytest.raises(ValueError, match="nested quantifiers"):
        _validate_css_selector("(?:a{100}){100}")


def test_repeated_quantified_groups_rejected() -> None:
    with pytest.raises(ValueError, match="quantified group"):
        _validate_css_selector("(a){100}")


def test_repeated_char_bomb_rejected() -> None:
    with pytest.raises(ValueError, match="repeated-character bomb"):
        _validate_css_selector("a" * 60)


def test_non_string_rejected() -> None:
    with pytest.raises(ValueError, match="must be a string"):
        _validate_css_selector(123)  # type: ignore[arg-type]


# ── integration: schema validation at entry points ──


def test_validate_schema_selectors_rejects_unsafe_base_selector() -> None:
    schema = {
        "name": "products",
        "base_selector": "(?:a{100}){100}",
        "fields": [{"name": "title", "selector": "h3", "type": "text"}],
    }
    with pytest.raises(ValueError, match="nested quantifiers"):
        validate_schema_selectors(schema)


def test_validate_schema_selectors_rejects_unsafe_field_selector() -> None:
    schema = {
        "name": "products",
        "base_selector": ".product",
        "fields": [{"name": "title", "selector": "a" * 60, "type": "text"}],
    }
    with pytest.raises(ValueError, match="repeated-character bomb"):
        validate_schema_selectors(schema)


def test_validate_schema_selectors_accepts_safe_schema() -> None:
    schema = {
        "name": "products",
        "base_selector": ".product-card",
        "fields": [
            {"name": "title", "selector": "h3", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
        ],
    }
    assert validate_schema_selectors(schema) is schema


def test_extract_structured_rejects_unsafe_base_selector() -> None:
    schema = {
        "name": "products",
        "base_selector": " > ".join(["div"] * 26),
        "fields": [{"name": "title", "selector": "h3", "type": "text"}],
    }
    with pytest.raises(ValueError, match="too many combinators"):
        asyncio.run(extract_structured("<html><body><div>hi</div></body></html>", schema))


def test_extract_structured_rejects_unsafe_field_selector() -> None:
    schema = {
        "name": "products",
        "base_selector": ".product",
        "fields": [{"name": "title", "selector": "(?:a{100}){100}", "type": "text"}],
    }
    with pytest.raises(ValueError, match="nested quantifiers"):
        asyncio.run(
            extract_structured("<html><body><div class='product'>hi</div></body></html>", schema)
        )


def test_strategy_extract_rejects_unsafe_base_selector() -> None:
    strategy = JsonCssExtractionStrategy(
        {
            "name": "products",
            "base_selector": "a" * 60,
            "fields": [{"name": "title", "selector": "h3", "type": "text"}],
        }
    )
    with pytest.raises(ValueError, match="repeated-character bomb"):
        strategy.extract("<html><body><h3>hi</h3></body></html>")
