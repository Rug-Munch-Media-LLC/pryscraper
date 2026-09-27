"""Shared sample-data fixtures.

Kept out of conftest.py so that file stays focused on test ISOLATION, which
is the part where a mistake silently couples two tests together.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import pytest


@pytest.fixture
def sample_html() -> str:
    return """<!DOCTYPE html><html><head><title>Test Page</title>
<meta name="description" content="A test page for scraping">
</head><body>
<h1 class="product-title">Widget Pro</h1>
<p class="price">$29.99</p>
<p class="description">The best widget ever made.</p>
<a href="https://example.com/page1">Page 1</a>
<a href="https://example.com/page2">Page 2</a>
<a href="https://external.com">External</a>
</body></html>"""


@pytest.fixture
def sample_markdown() -> str:
    return """# Widget Pro

**Price:** $29.99

The best widget ever made.

- Feature 1: Lightweight
- Feature 2: Durable
- Feature 3: Affordable

Contact: sales@example.com
"""


@pytest.fixture
def sample_schema() -> dict:
    return {
        "product_name": "name of the product",
        "price": "price in USD",
        "email": "contact email email",
    }


# ── Lenient LogRecord for tests ─────────────────────────────────
# Some Pry modules (and tests) use logger.warning("...", extra={"name": "foo"})
# patterns. Python's stdlib logging rejects this with KeyError because
# "name" is a reserved LogRecord field. In tests we make the LogRecord
# tolerant: reserved keys in `extra` are moved to a sub-dict so the call
# doesn't crash. This matches the behavior we get with structlog's bridge.
