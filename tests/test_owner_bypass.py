"""Owner-key bypass: the operator key skips preauth + per-key quota, but only it.

The bug this pins: with the owner key, ``/v1/scrape`` returned 429
``quota_unavailable`` (the fail-closed branch of an unverified quota bucket),
so the fleet could not call its own API during any quota-read outage — while an
external caller must keep getting the paywall / quota deny.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

import asyncio

import pytest

from pry.core import middleware_ratelimit as ratelimit
from pry.core.middleware_ratelimit import _OWNER_HEADERS, _owner_key
from pry.core.settings import settings

OWNER = "owner_test_key_1111111111"
EXTERNAL = "pry_test_key_00000000"
REQUIRED_HEADERS = {"x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"}


@pytest.fixture
def owner_configured():
    """Configure the operator key the way conftest configures settings."""

    previous = settings.api_key
    settings.api_key = OWNER
    try:
        yield
    finally:
        settings.api_key = previous


def _bearer(key: str) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/v1/scrape",
        "headers": [(b"authorization", f"Bearer {key}".encode())],
        "client": ("203.0.113.9", 5),
        "query_string": b"",
    }


def test_owner_key_bypasses_the_per_key_quota(owner_configured):
    allowed, stats, headers, api_key = asyncio.run(
        ratelimit.resolve_rate_limit(_bearer(OWNER), "203.0.113.9")
    )

    assert allowed is True
    assert stats["reason"] == "owner"
    assert api_key == OWNER
    # The send wrapper indexes all three unconditionally: a partial dict is a 500.
    assert set(headers) == REQUIRED_HEADERS
    assert headers == _OWNER_HEADERS


def test_external_key_is_not_treated_as_owner(owner_configured):
    assert _owner_key(EXTERNAL) is False
    assert _owner_key(OWNER) is True


@pytest.mark.parametrize("candidate", ["", "öwner", "owner_test_key_1111111112"])
def test_owner_key_compare_never_raises(owner_configured, candidate):
    assert _owner_key(candidate) is False
