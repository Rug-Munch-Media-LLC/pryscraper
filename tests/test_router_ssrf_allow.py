"""SSRF guard anti-regression: ordinary public scraping must keep working.

Pry scrapes arbitrary public sites by design, so the SSRF guard added to the
router layer (``pry.api.routers.scraping.fetch.guard_get``) is a filter, not a
gate. The failure mode this module exists to catch is a guard that "fixes" SSRF
by refusing normal internet traffic — every rejection test in
``test_router_ssrf_reject.py`` passes for such a guard, and only these fail.

Each test names the mutation it kills.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from tests.ssrf_harness import (
    PAGE,
    TABLE_PAGE,
    client,
)


@respx.mock
@pytest.mark.parametrize(
    ("route", "body"),
    [("/v1/schema", "https://example.com/page"), ("/v1/links", "https://example.com/page")],
    ids=["schema", "links"],
)
def test_normal_public_url_still_scrapes(route: str, body: str) -> None:
    """Kills: an over-broad guard — deny-by-default hostnames, or a
    scheme/host allowlist that rejects ordinary internet traffic.
    """
    respx.get(body).mock(return_value=httpx.Response(200, text=PAGE))

    r = client.post(route, json=body)

    assert r.status_code == 200, r.text
    assert r.json()["success"] is True


@respx.mock
def test_extract_table_public_url_is_not_blocked() -> None:
    """Kills: an over-broad guard on /v1/extract-table.

    Asserts only that the guarded fetch was permitted and issued — not the
    route's response. ``/v1/extract-table`` fails downstream for an unrelated,
    pre-existing reason: it calls ``pd.read_html(resp.text)`` and this pandas
    build reads a bare string as a *filename*, raising FileNotFoundError. That
    defect is out of scope here; what matters for SSRF is that the guard lets a
    public URL through and reaches the transport.
    """
    target = respx.get("https://example.com/table").mock(
        return_value=httpx.Response(200, text=TABLE_PAGE)
    )

    client.post("/v1/extract-table", json="https://example.com/table")

    assert target.called, "/v1/extract-table blocked an ordinary public URL"


@respx.mock
def test_normal_public_redirect_still_followed(empty_scrape: None) -> None:
    """Kills: a fix that re-validates redirects so strictly it refuses to
    follow them. http→https upgrades are the common case; refusing them would
    break every site that redirects.

    Uses /v1/extract/css: with ``empty_scrape`` the route's own guarded fetch is
    the only thing that talks to the network, so ``final.called`` proves the
    redirect chain was walked rather than short-circuited.
    """
    respx.get("http://example.com/page").mock(
        return_value=httpx.Response(301, headers={"location": "https://example.com/page"})
    )
    final = respx.get("https://example.com/page").mock(return_value=httpx.Response(200, text=PAGE))

    client.post("/v1/extract/css", json={"url": "http://example.com/page", "schema": {}})

    assert final.called, "a safe public redirect was not followed"


@respx.mock
def test_public_cross_site_redirect_still_followed() -> None:
    """Kills: a fix that pins a single host across the whole chain and so
    refuses a legitimate redirect to a CDN or a canonical domain. Off-allowlist
    means *internal*, not *different*.
    """
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(302, headers={"location": "https://cdn.example.org/page"})
    )
    cdn = respx.get("https://cdn.example.org/page").mock(
        return_value=httpx.Response(200, text=PAGE)
    )

    r = client.post("/v1/schema", json="https://example.com/page")

    assert r.status_code == 200, r.text
    assert cdn.called, "a public redirect to another public host was blocked"
