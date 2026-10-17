"""Happy-path tests for the SSRF-guarded engine/API-layer fetches.

Guards that only ever reject are useless, so these prove the two guarded call
sites still do their actual job after the fix:

* ``pry.api.enrichment.enrich_url`` (via ``POST /v1/enrich`` and
  ``POST /v1/enrich/tech-stack``) still fetches and analyses a public page.
* ``pry.engine.parser.DocumentParser.parse`` (via ``POST /v1/parse``) still
  fetches and parses a document.

``test_*_public_redirect_is_followed`` is the pair that matters most: the fix
replaced httpx's own redirect following with ``safe_get``'s manual loop, so a
regression that made redirects stop working would pass every rejection test in
``test_engine_fetch_ssrf_reject.py`` while quietly breaking the product.

The rejection half lives in ``test_engine_fetch_ssrf_reject.py``; the router
layer keeps its own pair in ``test_router_ssrf_reject.py`` /
``test_router_ssrf_allow.py``.
"""

from __future__ import annotations

import httpx
import respx

from tests.test_engine_fetch_ssrf_reject import client, enrich_body

#: A page that trips the tech-stack, social-profile and company-info extractors.
BUSINESS_PAGE = (
    "<html><head>"
    '<meta name="generator" content="WordPress 6.5">'
    '<script src="/wp-includes/js/jquery.min.js"></script>'
    '<link rel="stylesheet" href="https://cdn.shopify.com/s/x.css">'
    '<script async src="https://www.google-analytics.com/analytics.js"></script>'
    "</head><body>"
    '<a href="https://twitter.com/acme">@acme</a>'
    '<a href="https://github.com/acme">github</a>'
    "<p>Founded in 2011 with 250 employees.</p>"
    "<p>Contact: sales@acme.example or +1 555 123 4567</p>"
    "<p>123 Market Street, Springfield, CA 94105</p>"
    "</body></html>"
)

PUBLIC_URL = "https://acme.example.com/about"


@respx.mock
def test_enrich_fetches_and_analyses_a_public_page() -> None:
    """Kills: a guard wired in so that it never actually fetches (a stub client,
    an over-broad rejection, or a lost response body) — the fix must not trade a
    vulnerability for a dead feature.
    """
    page = respx.get(PUBLIC_URL).mock(
        return_value=httpx.Response(200, text=BUSINESS_PAGE, headers={"content-type": "text/html"})
    )

    r = client.post("/v1/enrich", json=enrich_body(PUBLIC_URL))

    assert r.status_code == 200, r.text[:300]
    data = r.json()["data"]
    assert page.called, "enrichment never fetched the page"
    assert "wordpress" in data["tech_stack"]["detected"]
    assert "shopify" in data["tech_stack"]["detected"]
    assert "google_analytics" in data["tech_stack"]["detected"]
    expected = ["wordpress", "shopify"]
    assert data["tech_stack"]["categories"]["cms"] == expected
    assert "twitter" in data["social_profiles"]["platforms_found"]
    assert "sales@acme.example" in data["company_info"]["emails"]
    assert data["company_info"]["founded_year"] == "2011"
    assert "error" not in data, f"unexpected error field: {data.get('error')}"


@respx.mock
def test_enrich_tech_stack_route_still_works() -> None:
    """Kills: a guard applied to one enrichment route but not the sibling that
    shares ``enrich_url``.
    """
    respx.get(PUBLIC_URL).mock(
        return_value=httpx.Response(200, text=BUSINESS_PAGE, headers={"content-type": "text/html"})
    )

    r = client.post("/v1/enrich/tech-stack", json=PUBLIC_URL)

    assert r.status_code == 200, r.text[:300]
    assert "wordpress" in r.json()["data"]["detected"]


@respx.mock
def test_enrich_still_short_circuits_when_html_is_supplied() -> None:
    """Kills: a guard that ignores caller-supplied HTML and fetches anyway — an
    unnecessary outbound request on every call.
    """
    respx.get(PUBLIC_URL).mock(return_value=httpx.Response(200, text="<html>fetched</html>"))
    # ``enrich_url`` is also reachable with html pre-supplied (not via a route);
    # assert the short-circuit at the function so the route shape cannot hide it.
    import asyncio

    from pry.api.enrichment import enrich_url

    result = asyncio.run(enrich_url(PUBLIC_URL, html=BUSINESS_PAGE))

    assert "wordpress" in result["tech_stack"]["detected"]
    assert not respx.calls.called, "fetched despite html being supplied"


@respx.mock
def test_parse_fetches_and_parses_a_public_document() -> None:
    """Kills: a guard wired into ``DocumentParser.parse`` that stops it fetching
    or breaks the hand-off of content/content-type to the format dispatch.
    """
    doc = respx.get("https://files.example.com/report.json").mock(
        return_value=httpx.Response(
            200,
            json={"revenue": 42, "region": "EMEA"},
            headers={"content-type": "application/json"},
        )
    )

    r = client.post("/v1/parse", json={"url": "https://files.example.com/report.json"})

    assert r.status_code == 200, r.text[:300]
    assert doc.called, "parse never fetched the document"
    data = r.json()["data"]
    assert data["format"] == "json"
    assert "revenue" in data["text"]


@respx.mock
def test_enrich_public_redirect_is_followed() -> None:
    """Kills: replacing httpx's redirect following with a manual loop that
    stops at the first 3xx. Enrichment of a public URL that redirects is
    ordinary web behaviour and must keep working.
    """
    respx.get(PUBLIC_URL).mock(
        return_value=httpx.Response(301, headers={"location": "https://www.acme.example.com/about"})
    )
    final = respx.get("https://www.acme.example.com/about").mock(
        return_value=httpx.Response(200, text=BUSINESS_PAGE, headers={"content-type": "text/html"})
    )

    r = client.post("/v1/enrich", json=enrich_body(PUBLIC_URL))

    assert r.status_code == 200, r.text[:300]
    assert final.called, "the public redirect was not followed"
    assert "wordpress" in r.json()["data"]["tech_stack"]["detected"]


@respx.mock
def test_parse_public_redirect_is_followed() -> None:
    """Kills: the same regression on the parser path, which is where the
    redirect behaviour moved off the client constructor.
    """
    respx.get("https://files.example.com/doc").mock(
        return_value=httpx.Response(302, headers={"location": "https://cdn.example.com/doc.txt"})
    )
    final = respx.get("https://cdn.example.com/doc.txt").mock(
        return_value=httpx.Response(200, text="plain body", headers={"content-type": "text/plain"})
    )

    r = client.post("/v1/parse", json={"url": "https://files.example.com/doc"})

    assert r.status_code == 200, r.text[:300]
    assert final.called, "the public redirect was not followed"
    assert r.json()["data"]["format"] == "text"


@respx.mock
def test_enrich_reports_unreadable_source_as_4xx() -> None:
    """Kills: over-correcting the transport branch into a 5xx, and the mirror
    error of swallowing it into a 200 whose body is indistinguishable from a
    page with nothing on it. The route returns a fixed field set, so a dropped
    reason would be invisible — an unreadable source must be a visible 4xx.
    """
    respx.get("https://down.example.com/").mock(side_effect=httpx.ConnectError("refused"))

    r = client.post("/v1/enrich", json=enrich_body("https://down.example.com/"))

    assert r.status_code == 400, r.text[:300]
    assert "ConnectError" in r.json()["detail"]


@respx.mock
def test_enrich_reports_non_2xx_source_as_4xx() -> None:
    """Kills: dropping a 404/500 response body and reporting empty enrichment as
    a success, which reads as "this site has no tech stack".
    """
    respx.get("https://gone.example.com/").mock(return_value=httpx.Response(404, text="nope"))

    r = client.post("/v1/enrich", json=enrich_body("https://gone.example.com/"))

    assert r.status_code == 400, r.text[:300]
    assert "404" in r.json()["detail"]
