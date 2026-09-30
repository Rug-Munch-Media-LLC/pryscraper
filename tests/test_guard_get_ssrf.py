"""Unit tests for the shared SSRF guard wrapper.

Split from test_ai_suggest_ssrf.py to stay under the 200-line structure cap.
Route-level SSRF coverage stays there; these exercise guard_get directly.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import httpx
import pytest
import respx

from pry.core.errors import InvalidRequestError
from tests.ssrf_harness import METADATA, client, guard_get_sync

#: Internal first-hop targets, across the shapes a metadata-IP-only block misses.
INTERNAL_URLS: list[str] = [
    METADATA,
    "http://127.0.0.1:8080/admin",
    "http://localhost:8080/admin",
    "file:///etc/passwd",
    "http://[::1]/admin",
    "http://10.0.0.1/admin",
]
INTERNAL_IDS = [
    "metadata",
    "loopback-ip",
    "loopback-name",
    "file-scheme",
    "loopback-ipv6",
    "rfc1918",
]

#: A product page whose markup is what the route is designed to read. The
#: selectors are standalone quoted tokens because the route's regexes anchor on
#: the quote characters, not on a class attribute.
SUGGEST_PAGE = (
    "<html><body>"
    '<span class="price">$9.99</span>'
    '<h1 class="product-title">Widget</h1>'
    "</body></html>"
)


# ── the guard primitive itself, on the same shapes ─────────────────────────


@respx.mock
@pytest.mark.parametrize("url", INTERNAL_URLS, ids=INTERNAL_IDS)
def test_guard_get_rejects_internal_url(url: str) -> None:
    """Kills: a regression in the wrapper the route calls — e.g. re-adding a
    ``follow_redirects`` passthrough, or defaulting ``user_agent`` to something
    the transport treats specially. The route-level tests above assert on
    behaviour; this one pins the exception the route propagates.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text="internal-secret"))

    with pytest.raises(InvalidRequestError):
        guard_get_sync(url)

    assert not catch_all.called


# ── anti-regression: normal public scraping must still work ────────────────


@respx.mock
def test_normal_public_url_still_suggested() -> None:
    """Kills: an over-broad guard on ``/v1/suggest`` — deny-by-default
    hostnames, or an allowlist that rejects ordinary internet traffic. Every
    rejection test in this module passes for such a guard; only this one fails.
    """
    target = respx.get("https://example.com/product").mock(
        return_value=httpx.Response(200, text=SUGGEST_PAGE)
    )

    r = client.post("/v1/suggest", json={"url": "https://example.com/product"})

    assert r.status_code == 200, r.text
    assert target.called, "/v1/suggest blocked an ordinary public URL"
    data = r.json()["data"]
    assert "price" in data["suggested"], data
    assert "html_error" not in data, data


@respx.mock
def test_normal_public_redirect_still_followed() -> None:
    """Kills: a fix that re-validates redirects so strictly it refuses to
    follow them. http→https upgrades are the common case; refusing them would
    break every site that redirects.
    """
    respx.get("http://example.com/product").mock(
        return_value=httpx.Response(301, headers={"location": "https://example.com/product"})
    )
    final = respx.get("https://example.com/product").mock(
        return_value=httpx.Response(200, text=SUGGEST_PAGE)
    )

    r = client.post("/v1/suggest", json={"url": "http://example.com/product"})

    assert r.status_code == 200, r.text
    assert final.called, "a safe public redirect was not followed"
    assert "price" in r.json()["data"]["suggested"], r.text
