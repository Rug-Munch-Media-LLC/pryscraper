"""SSRF guard anti-regression: normal monitoring must keep working.

The actor-layer guard added to ``pry.actors.seo_monitor`` and
``pry.actors.structure_monitor`` is a filter, not a gate — Pry monitors
arbitrary public competitor pages by design. The failure mode this module
exists to catch is a guard that "fixes" SSRF by refusing ordinary internet
traffic: every rejection test in ``test_actor_ssrf_reject.py`` passes for such
a guard, and only these fail.

Two properties are asserted, and they are not the same:
``allowed`` proves the guarded fetch was *permitted and issued* (the SSRF
property — the transport was reached); ``parsed`` proves the actor still
returns a correct SEO/structure result (the regression property).

Each test names the mutation it kills.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from tests.ssrf_actor_harness import (
    FINAL_PAGE,
    PAGE,
    REDIRECTOR,
    client,
)

PUBLIC = "https://competitor.example.com/page"


@respx.mock
@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("/v1/seo/analyze", PUBLIC),
        ("/v1/seo/track", PUBLIC),
        ("/v1/seo/keywords", {"url": PUBLIC, "keywords": ["alpha"]}),
        ("/v1/structure/check", {"url": PUBLIC, "selectors": [{"selector": "h1"}]}),
        ("/v1/structure/monitor", {"url": PUBLIC, "selectors": [{"selector": "h1"}]}),
    ],
    ids=["seo-analyze", "seo-track", "seo-keywords", "structure-check", "structure-monitor"],
)
def test_normal_public_url_is_never_blocked(
    route: str, body: object, resolved_dns: str
) -> None:
    """Kills: an over-broad guard — deny-by-default hostnames, or a
    scheme/host allowlist that refuses ordinary internet traffic.

    Asserts only that the guarded fetch was permitted and issued, not the
    route's response: the SSRF property is "the transport was reached", and
    that stays true whichever way the route handles the body afterwards.
    """
    target = respx.get(f"https://{resolved_dns}/page").mock(return_value=httpx.Response(200, text=PAGE))

    r = client.post(route, json=body)

    assert target.called, f"{route} blocked an ordinary public URL: {r.text}"


@respx.mock
def test_seo_analyze_returns_parsed_elements(resolved_dns: str) -> None:
    """Kills: a fix that routes the fetch through the guard but breaks the
    parsing — a bare ``validate_url`` + ``client.get`` swap that drops the
    browser User-Agent, or a ``safe_get`` call that loses the response body.
    """
    respx.get(f"https://{resolved_dns}/page").mock(return_value=httpx.Response(200, text=PAGE))

    r = client.post("/v1/seo/analyze", json=PUBLIC)

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert r.json()["success"] is True
    assert data["title"] == "Example Domain"
    expected = ["Example"]
    assert data["h1"] == expected
    assert data["meta_description"] == "An example page"


@respx.mock
def test_seo_keywords_finds_a_matching_keyword(resolved_dns: str) -> None:
    """Kills: a fix to the ``get_seo_keyword_insights`` fetch that leaves the
    actor returning an error payload — the guard wired in but the response no
    longer reaches the keyword analysis.
    """
    respx.get(f"https://{resolved_dns}/page").mock(return_value=httpx.Response(200, text=PAGE))

    r = client.post("/v1/seo/keywords", json={"url": PUBLIC, "keywords": ["alpha"]})

    assert r.status_code == 200, r.text
    results = r.json()["data"]["results"]
    assert len(results) == 1
    assert results[0]["keyword"] == "alpha"
    assert results[0]["frequency"] == 1, results[0]


@respx.mock
def test_structure_check_reports_a_match(resolved_dns: str) -> None:
    """Kills: a fix to the ``check_selectors`` fetch that leaves the actor
    returning ``all_matched: False`` for a selector that is present — the
    guard wired in but the parsed HTML no longer reaching the selector engine.
    """
    respx.get(f"https://{resolved_dns}/page").mock(return_value=httpx.Response(200, text=PAGE))

    r = client.post("/v1/structure/check", json={"url": PUBLIC, "selectors": [{"selector": "h1"}]})

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["all_matched"] is True, data
    assert data["matched_count"] == 1, data


@respx.mock
def test_normal_public_redirect_is_followed(resolved_dns: str) -> None:
    """Kills: a fix that re-validates redirects so strictly it refuses to
    follow them at all. http→https upgrades and canonical-domain hops are the
    common case; refusing them would break every site that redirects.
    """
    respx.get(f"http://{resolved_dns}/page").mock(
        return_value=httpx.Response(301, headers={"location": PUBLIC})
    )
    final = respx.get(f"https://{resolved_dns}/page").mock(return_value=httpx.Response(200, text=PAGE))

    r = client.post("/v1/seo/analyze", json="http://competitor.example.com/page")

    assert final.called, "a safe public redirect was not followed"
    assert r.status_code == 200, r.text
    assert r.json()["data"]["title"] == "Example Domain"


@respx.mock
def test_public_cross_site_redirect_is_followed(resolved_dns: str) -> None:
    """Kills: a fix that pins a single host across the whole redirect chain
    and so refuses a legitimate hop to a CDN or a canonical domain.
    Off-allowlist means *internal*, not *different*.
    """
    respx.get(f"https://{resolved_dns}/go").mock(
        return_value=httpx.Response(302, headers={"location": PUBLIC})
    )
    final = respx.get(f"https://{resolved_dns}/page").mock(return_value=httpx.Response(200, text=FINAL_PAGE))

    r = client.post("/v1/seo/analyze", json=REDIRECTOR)

    assert final.called, "a public redirect to another public host was blocked"
    assert r.status_code == 200, r.text
    assert r.json()["data"]["title"] == "Final Domain"


@respx.mock
def test_upstream_4xx_is_reported_not_swallowed(resolved_dns: str) -> None:
    """Kills: a guard that masks the target's own HTTP status as a rejection.
    A public page answering 404 is a real SEO finding; the monitor must say so
    rather than reporting a guard failure the caller cannot act on.
    """
    respx.get(f"https://{resolved_dns}/page").mock(return_value=httpx.Response(404, text="not found"))

    r = client.post("/v1/seo/analyze", json=PUBLIC)

    assert r.status_code == 200, r.text
    assert r.json()["data"]["error"] == "HTTP 404", r.json()
