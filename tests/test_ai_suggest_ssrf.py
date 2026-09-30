"""SSRF rejection tests for ``POST /v1/suggest``.

``suggest_schema`` reads ``url`` straight from the request body and fetched the
page's raw HTML with a bare ``client.get(url, ...)`` — no scheme check, no
private-range check, no re-validation of anything the server redirected to. The
route is not in the public-path allowlist, so it is API-key gated rather than
fully open, but a key is not an SSRF boundary: any caller with a key could reach
the cloud metadata service at 169.254.169.254 and read it back in the
``suggested`` selectors.

It now goes through ``guard_get``, which delegates to ``url_guard.safe_get``:
the initial URL is validated and every ``Location`` target is re-validated before
the next hop. The guard runs BEFORE the scraper, so a rejected target is refused
before any layer opens a connection to it.

Each test names the mutation it kills. The companion module
``test_router_ssrf_allow.py`` proves the guard does not break ordinary public
scraping through this route.
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

from tests.ssrf_harness import LEAK_BODY, METADATA, client

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


@respx.mock
@pytest.mark.parametrize("url", INTERNAL_URLS, ids=INTERNAL_IDS)
def test_suggest_never_connects_to_an_internal_url(url: str) -> None:
    """Kills: reverting ``/v1/suggest`` to a bare ``client.get(url)``.

    Asserts on *whether a connection was issued* rather than on a status code:
    that is the property that matters, and it fails even if a later change
    swallows the guard's exception. The leaked-payload assertion closes the
    other direction — a guard rejection that still returned fetched content.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post("/v1/suggest", json={"url": url})

    assert not catch_all.called, f"/v1/suggest opened a connection to {url}"
    assert LEAK_BODY not in r.text, "/v1/suggest returned metadata-service content"


@respx.mock
@pytest.mark.parametrize("url", INTERNAL_URLS, ids=INTERNAL_IDS)
def test_suggest_rejects_internal_url_with_4xx_not_500(url: str) -> None:
    """Kills: catching only ``httpx`` errors around the guarded fetch, so the
    guard's ``InvalidRequestError`` escapes as an unhandled 500.

    The guard raises a ``PryError`` carrying ``status_code`` 400. A route whose
    ``except`` clause lists only ``httpx.HTTPError`` never sees it, so the
    rejection reaches the client as a 500 — the request failed, but as a
    server fault rather than a client-visible refusal.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post("/v1/suggest", json={"url": url})

    assert 400 <= r.status_code < 500, f"expected a 4xx rejection, got {r.status_code}: {r.text}"
    assert not catch_all.called


@respx.mock
def test_suggest_guard_runs_before_the_scraper() -> None:
    """Kills: a fix that keeps the bare ``client.get`` but adds a guard call
    *after* the scrape — the scraper would already have connected to the target.

    Both layers are mocked at the transport, so "was anything connected at all"
    is the only honest question.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text=LEAK_BODY))

    client.post("/v1/suggest", json={"url": METADATA})

    assert not catch_all.called, "the target was contacted before the guard refused it"


@respx.mock
def test_suggest_rejects_a_redirect_to_metadata() -> None:
    """Kills: the "validate the submitted URL, then follow redirects" fix.

    The submitted URL is a valid public page, so a one-shot ``validate_url(url)`
    before an unguarded fetch approves it — and then httpx follows the 302 with
    nothing re-checking the destination. Only per-hop re-validation stops this.
    The first hop is *expected* to be fetched: rejecting it too would mean the
    test passes for the wrong reason.
    """
    first_hop = respx.get("https://redirector.example.com/go").mock(
        return_value=httpx.Response(302, headers={"location": METADATA})
    )
    metadata = respx.get(METADATA).mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post("/v1/suggest", json={"url": "https://redirector.example.com/go"})

    assert first_hop.called, "the public first hop should still be fetched"
    assert not metadata.called, "followed a redirect to the metadata service"
    assert 400 <= r.status_code < 500, r.text


@respx.mock
def test_suggest_rejects_a_redirect_to_loopback() -> None:
    """Kills: re-validating only the metadata address, or only the first
    redirect hop. Loopback is a different private range with a different payoff
    (local admin ports), so it is a separate attack, not a duplicate case.
    """
    respx.get("https://redirector.example.com/go").mock(
        return_value=httpx.Response(301, headers={"location": "http://127.0.0.1:8080/admin"})
    )
    loopback = respx.get("http://127.0.0.1:8080/admin").mock(
        return_value=httpx.Response(200, text="internal-secret")
    )

    r = client.post("/v1/suggest", json={"url": "https://redirector.example.com/go"})

    assert not loopback.called
    assert 400 <= r.status_code < 500, r.text


@respx.mock
def test_suggest_rejects_a_redirect_to_a_non_http_scheme() -> None:
    """Kills: a redirect check that only inspects resolved addresses and so
    lets a ``file://`` Location through — an address check has nothing to say
    about a scheme that never resolves.
    """
    respx.get("https://redirector.example.com/go").mock(
        return_value=httpx.Response(302, headers={"location": "file:///etc/passwd"})
    )
    catch_all = respx.route().mock(return_value=httpx.Response(200, text="root:x:0:0"))

    r = client.post("/v1/suggest", json={"url": "https://redirector.example.com/go"})

    assert not catch_all.called, "followed a redirect to a file:// target"
    assert 400 <= r.status_code < 500, r.text


@respx.mock
def test_suggest_stops_a_redirect_chain_at_the_offending_hop() -> None:
    """Kills: a fix that re-validates only the *first* redirect, or that
    validates but still follows. Two safe hops, then an internal third.
    """
    respx.get("https://a.example.com/1").mock(
        return_value=httpx.Response(302, headers={"location": "https://b.example.com/2"})
    )
    respx.get("https://b.example.com/2").mock(
        return_value=httpx.Response(302, headers={"location": METADATA})
    )
    metadata = respx.get(METADATA).mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post("/v1/suggest", json={"url": "https://a.example.com/1"})

    assert not metadata.called
    assert 400 <= r.status_code < 500, r.text


