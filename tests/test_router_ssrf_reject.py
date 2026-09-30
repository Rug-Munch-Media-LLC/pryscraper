"""SSRF rejection tests for the scraping routers' guarded fetch.

Eight router routes (``/v1/extract-table``, ``/v1/links``, ``/v1/thumbnail``,
``/v1/seo``, ``/v1/schema``, ``/v1/emails``, ``/v1/extract/css``,
``/v1/shadow-dom``) fetched a caller-supplied URL with a bare ``client.get``.
The engine tiers validate every hop through ``url_guard``; the router layer
bypassed them, so an unauthenticated request could reach the cloud metadata
service at 169.254.169.254 — and where ``follow_redirects=True`` was set, any
open redirector walked a *valid* public URL off the allowlist.

Each test drives a real route over the ASGI app and asserts on **whether a
connection was issued**, not on a status code: the routes disagree about how to
report a rejection (``/v1/links`` degrades to empty, ``/v1/thumbnail`` reports
best-effort failure), but all of them agree they must not connect.

The companion module ``test_router_ssrf_allow.py`` proves the guard does not
break ordinary public scraping.

Every test names the mutation it kills.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from pry.core.errors import InvalidRequestError
from tests.ssrf_harness import (
    LEAK_BODY,
    METADATA,
    client,
    guard_get_sync,
)

#: Every route that fetches a caller-supplied URL, with the body it accepts.
#: ``/v1/extract/css`` takes an object body; the rest take a bare URL string.
CRAWL_ROUTES: list[tuple[str, object]] = [
    ("/v1/extract-table", METADATA),
    ("/v1/links", METADATA),
    ("/v1/thumbnail", METADATA),
    ("/v1/seo", METADATA),
    ("/v1/schema", METADATA),
    ("/v1/emails", METADATA),
    ("/v1/extract/css", {"url": METADATA, "schema": {}}),
    ("/v1/shadow-dom", METADATA),
]
ROUTE_IDS = [name for name, _ in CRAWL_ROUTES]


# ── first hop: the internal target is never connected ─────────────────────


@respx.mock
@pytest.mark.parametrize(("route", "body"), CRAWL_ROUTES, ids=ROUTE_IDS)
def test_cloud_metadata_is_never_fetched(route: str, body: object, empty_scrape: None) -> None:
    """Kills: reverting any of the eight routes to a bare ``client.get(url)``
    (or re-adding ``follow_redirects=True``).

    A leak shows up two ways — the catch-all route is called, or the response
    body carries the metadata payload. Both are asserted, so the test cannot
    pass while the fetch succeeds.

    ``empty_scrape`` matters for the two fallback-fetch routes
    (``/v1/extract/css``, ``/v1/shadow-dom``): without it they return after the
    real scraper's failed network attempt and never reach the guarded fetch.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post(route, json=body)

    assert not catch_all.called, f"{route} opened a connection to the target"
    assert LEAK_BODY not in r.text, f"{route} returned metadata-service content"


@respx.mock
@pytest.mark.parametrize(
    "bad_url",
    [
        "http://127.0.0.1:8080/admin",
        "http://localhost:8080/admin",
        "file:///etc/passwd",
        "http://[::1]/admin",
        "http://10.0.0.1/admin",
    ],
    ids=["loopback-ip", "loopback-name", "file-scheme", "loopback-ipv6", "rfc1918"],
)
def test_internal_first_hop_is_never_fetched(bad_url: str) -> None:
    """Kills: an unguarded fetch, across targets a metadata-IP-only block would
    not catch. Five distinct internal shapes, one assertion: no connection.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text="internal-secret"))

    with pytest.raises(InvalidRequestError):
        guard_get_sync(bad_url)

    assert not catch_all.called, f"guard_get fetched a rejected target: {bad_url}"


# ── the redirect case: what a single validate_url cannot catch ────────────


@respx.mock
@pytest.mark.parametrize(
    ("location", "target"),
    [
        ("http://169.254.169.254/latest/meta-data/", METADATA),
        ("http://127.0.0.1:8080/admin", "http://127.0.0.1:8080/admin"),
        ("file:///etc/passwd", "file:///etc/passwd"),
    ],
    ids=["to-metadata", "to-loopback", "to-file-scheme"],
)
def test_public_redirect_off_allowlist_is_rejected(location: str, target: str) -> None:
    """Kills: the "validate the first URL, then follow redirects" fix — the
    mistake that survives a first-hop-only guard.

    The submitted URL is a valid public page, so a one-shot ``validate_url(url)`
    before an unguarded fetch approves it, and then httpx follows the 302 with
    nothing re-checking it. Only per-hop re-validation stops this.

    The first hop *is* expected to be fetched: proving the public URL was
    rejected for the wrong reason would hide the real bug.
    """
    first_hop = respx.get("https://redirector.example.com/go").mock(
        return_value=httpx.Response(302, headers={"location": location})
    )
    off_allowlist = respx.route(host=httpx.URL(target).host or "").mock(
        return_value=httpx.Response(200, text="internal-secret")
    )

    with pytest.raises(InvalidRequestError):
        guard_get_sync("https://redirector.example.com/go")

    assert first_hop.called, "the public first hop should still be fetched"
    assert not off_allowlist.called, "followed a redirect to an off-allowlist target"


@respx.mock
def test_redirect_chain_stops_at_the_offending_hop() -> None:
    """Kills: a fix that re-validates only the *first* redirect, or that
    validates but still follows. Two safe hops, then an internal third.
    """
    respx.get("https://a.example.com/1").mock(
        return_value=httpx.Response(302, headers={"location": "https://b.example.com/2"})
    )
    respx.get("https://b.example.com/2").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
    )
    metadata = respx.get("http://169.254.169.254/latest/").mock(
        return_value=httpx.Response(200, text="secret")
    )

    with pytest.raises(InvalidRequestError):
        guard_get_sync("https://a.example.com/1")

    assert not metadata.called
