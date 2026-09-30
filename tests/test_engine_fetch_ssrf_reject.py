"""SSRF rejection tests for the ENGINE/API-layer fetches behind two free routes.

Two call sites fetched a caller-supplied URL without the guard the router layer
already uses:

* ``pry.api.enrichment.enrich_url`` — ``client.get(url, timeout=20,
  follow_redirects=True)``, reached by ``POST /v1/enrich`` and
  ``POST /v1/enrich/tech-stack``.
* ``pry.engine.parser.DocumentParser.parse`` — ``client.get(url)`` on a client
  built ``follow_redirects=True``, reached by ``POST /v1/parse`` (rejection half
  in ``test_parse_fetch_ssrf.py``, which also covers the constructor flag).

Both routes are unauthenticated when the deployment sets no ``PRY_API_KEY``
(``pry.core.middleware_auth.request_authorized`` falls back to loopback-only),
so a rejection must be a clean 4xx rather than a 500.

The parser site is the subtle one: its redirect-following lived on the CLIENT,
not the call, so swapping the call for a guarded one while leaving
``follow_redirects=True`` on the constructor would validate hop one and then
follow every later hop unvalidated. ``test_parser_*`` therefore asserts on
connections issued, not on status codes.

Every test names the mutation it kills. The companion modules
``test_router_ssrf_reject.py`` / ``test_router_ssrf_allow.py`` cover the router
layer, ``test_engine_fetch_ssrf_allow.py`` covers the happy path here, and
``test_parse_fetch_ssrf.py`` covers the parser site (split out for the 200-line
structure cap).
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.exception_handlers import add_error_handlers
from pry.api.routers.data.enrichment import router as enrichment_router
from pry.api.routers.scraping.parsing import router as parsing_router

app = FastAPI()
app.include_router(enrichment_router)
app.include_router(parsing_router)
# The real app installs the PryError -> status_code mapping; without it a guard
# refusal would surface as a bare 500 and the 4xx assertions would measure the
# harness rather than the route.
add_error_handlers(app)
client = TestClient(app, raise_server_exceptions=False)

METADATA = "http://169.254.169.254/latest/meta-data/"
#: Payload a leaked internal response would carry.
LEAK_BODY = "INSTANCE_ID=leaked"


#: The two entry points, with the body each route accepts. ``/v1/enrich`` and
#: ``/v1/enrich/tech-stack`` take a bare URL string; ``/v1/parse`` takes an
#: object body.
def enrich_body(url: str) -> dict[str, object]:
    """``/v1/enrich`` declares four required ``Body(...)`` params."""
    return {
        "url": url,
        "include_tech_stack": True,
        "include_social": True,
        "include_company": True,
    }


FETCH_ROUTES: list[tuple[str, object]] = [
    ("/v1/enrich", enrich_body(METADATA)),
    ("/v1/enrich/tech-stack", METADATA),
    ("/v1/parse", {"url": METADATA, "timeout": 5}),
]
ROUTE_IDS = [name for name, _ in FETCH_ROUTES]


@respx.mock
@pytest.mark.parametrize(("route", "body"), FETCH_ROUTES, ids=ROUTE_IDS)
def test_metadata_target_is_never_fetched(route: str, body: object) -> None:
    """Kills: reverting either site to a bare ``client.get``.

    A leak shows up two ways — the catch-all route is called, or the response
    body carries the metadata payload. Both are asserted, so the test cannot
    pass while the fetch succeeds.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text=LEAK_BODY))

    r = client.post(route, json=body)

    assert not catch_all.called, f"{route} opened a connection to the metadata target"
    assert LEAK_BODY not in r.text, f"{route} returned metadata-service content"


@respx.mock
@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("/v1/enrich", enrich_body("http://127.0.0.1:8080/admin")),
        ("/v1/parse", {"url": "http://127.0.0.1:8080/admin", "timeout": 5}),
    ],
    ids=["enrich-loopback", "parse-loopback"],
)
def test_loopback_target_is_never_fetched(route: str, body: object) -> None:
    """Kills: a guard that only special-cases the metadata IP rather than
    rejecting the whole private/reserved range.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text="internal-secret"))

    client.post(route, json=body)

    assert not catch_all.called, f"{route} opened a connection to a loopback target"


@respx.mock
@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("/v1/enrich", enrich_body("file:///etc/passwd")),
        ("/v1/parse", {"url": "file:///etc/passwd", "timeout": 5}),
    ],
    ids=["enrich-file-scheme", "parse-file-scheme"],
)
def test_file_scheme_is_rejected(route: str, body: object) -> None:
    """Kills: a guard that validates the host but forgets the scheme, which is
    how a ``file://`` read or a local-socket probe gets through.
    """
    catch_all = respx.route().mock(return_value=httpx.Response(200, text="root:x:0:0"))

    r = client.post(route, json=body)

    assert not catch_all.called, f"{route} accepted a file:// URL"
    assert "root:x:0:0" not in r.text, f"{route} returned local file content"
    assert r.status_code == 400, f"{route}: expected 400, got {r.status_code}"


@respx.mock
@pytest.mark.parametrize(
    ("route", "body", "public"),
    [
        (
            "/v1/enrich",
            enrich_body("https://redirector.example.com/go"),
            "https://redirector.example.com/go",
        ),
        (
            "/v1/parse",
            {"url": "https://redirector.example.com/go", "timeout": 5},
            "https://redirector.example.com/go",
        ),
    ],
    ids=["enrich", "parse"],
)
def test_public_redirect_to_metadata_is_rejected(route: str, body: object, public: str) -> None:
    """Kills: "validate the first URL, then follow redirects" — the mistake that
    survives a first-hop-only guard.

    The submitted URL is a valid public page, so a one-shot ``validate_url(url)``
    before an unguarded fetch approves it, and httpx then follows the 302 with
    nothing re-checking it. The first hop is expected to be fetched: proving the
    public URL was refused for the wrong reason would hide the real bug.
    """
    first_hop = respx.get(public).mock(
        return_value=httpx.Response(302, headers={"location": METADATA})
    )
    metadata = respx.get(METADATA).mock(return_value=httpx.Response(200, text=LEAK_BODY))

    client.post(route, json=body)

    assert first_hop.called, "the public first hop should still be fetched"
    assert not metadata.called, f"{route} followed a redirect to the metadata service"
