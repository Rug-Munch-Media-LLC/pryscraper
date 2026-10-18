"""SSRF guard anti-regression: ordinary public scraping must keep working.

Pry scrapes arbitrary public sites by design, so the SSRF guard added to the
router layer (``pry.engine.fetch_guard.guard_get``) is a filter, not a
gate. The failure mode this module exists to catch is a guard that "fixes" SSRF
by refusing normal internet traffic — every rejection test in
``test_router_ssrf_reject.py`` passes for such a guard, and only these fail.

Each test names the mutation it kills.
"""

from __future__ import annotations

import httpx
import pytest

@pytest.fixture(autouse=True)
def _preserve_hostname(monkeypatch):
    """Keep the logical hostname so respx routes match.

    These tests assert that *ordinary public URLs are allowed*; the IP-pinning
    path is covered by test_url_guard/test_ssrf_redirect_hop. Resolve to a fixed
    public address (no live DNS) and skip the URL rewrite.
    """
    from pry.engine import url_pinning
    from pry.engine.url_guard import socket as guard_socket

    monkeypatch.setattr(
        guard_socket, "getaddrinfo",
        lambda *a, **k: [(guard_socket.AF_INET, guard_socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    monkeypatch.setattr(url_pinning, "pin_request", lambda url, *a, **k: (url, {}, {}))

import respx

from tests.ssrf_harness import (
    MULTI_TABLE_PAGE,
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
    route's response — because the SSRF property is "the transport was reached",
    and that stays true whichever way the route handles the body afterwards.
    The route's own parsing is covered by
    ``test_extract_table_returns_parsed_tables``.
    """
    target = respx.get("https://example.com/table").mock(
        return_value=httpx.Response(200, text=TABLE_PAGE)
    )

    client.post("/v1/extract-table", json="https://example.com/table")

    assert target.called, "/v1/extract-table blocked an ordinary public URL"


@respx.mock
def test_extract_table_returns_parsed_tables() -> None:
    """Kills: ``pd.read_html(resp.text)`` — the bare-string form.

    ``read_html``'s first parameter is ``FilePath | ReadBuffer[str]``, so a
    ``str`` is read as a *filename*: the route raised FileNotFoundError on
    every HTML response and had never worked. A test that only asserted the
    guard let the URL through passed against that broken route, which is why
    this one asserts on the parsed result.
    """
    respx.get("https://example.com/table").mock(
        return_value=httpx.Response(200, text=MULTI_TABLE_PAGE)
    )

    r = client.post("/v1/extract-table", json="https://example.com/table")

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["total_tables"] == 2
    expected = [{"Region": "EMEA", "Revenue": 10}]
    assert data["rows"] == expected
    assert data["table_index"] == 0


@respx.mock
def test_extract_table_index_selects_the_requested_table() -> None:
    """Kills: a fix that parses the buffer but ignores ``table_index`` and
    always returns the first table — ``table_index`` is a caller parameter, so
    silently dropping it is a wrong answer rather than a missing one.
    """
    respx.get("https://example.com/table").mock(
        return_value=httpx.Response(200, text=MULTI_TABLE_PAGE)
    )

    r = client.post("/v1/extract-table?table_index=1", json="https://example.com/table")

    assert r.status_code == 200, r.text
    expected = [{"Region": "APAC", "Revenue": 20}]
    assert r.json()["data"]["rows"] == expected


@respx.mock
def test_extract_table_out_of_range_index_is_rejected() -> None:
    """Kills: removing the bounds check, or letting pandas raise past the end of
    the list, so a caller asking for table 9 of a 2-table page gets a stack
    trace instead of a stated limit.
    """
    respx.get("https://example.com/table").mock(
        return_value=httpx.Response(200, text=MULTI_TABLE_PAGE)
    )

    r = client.post("/v1/extract-table?table_index=9", json="https://example.com/table")

    assert 400 <= r.status_code < 500, f"expected a 4xx, got {r.status_code}: {r.text}"
    assert "2 tables" in r.text


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
