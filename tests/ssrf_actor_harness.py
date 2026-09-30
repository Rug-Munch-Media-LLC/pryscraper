"""ASGI harness for the actor-layer SSRF regression tests.

``pry.actors.seo_monitor`` and ``pry.actors.structure_monitor`` sit *below* the
router layer, so the router harness in ``tests/ssrf_harness.py`` cannot reach
them without also standing up every router. This module builds a bare app
containing only the two SEO/structure routers, so a test drives a real route
end-to-end and any network attempt is observable.

``respx`` replaces the httpx transport globally while a test runs, so nothing
here (or in the actors under test) opens a socket.

``add_error_handlers`` matters: without it a ``PryError`` escaping the actor
would be a bare 500 rather than the ``InvalidRequestError`` 400 the real app
returns, and "a rejected URL yields a 4xx" would be untestable.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.exception_handlers import add_error_handlers
from pry.api.routers.scraping.seo import router as seo_router
from pry.api.routers.scraping.structure import router as structure_router

app = FastAPI()
app.include_router(seo_router)
app.include_router(structure_router)
add_error_handlers(app)
client = TestClient(app, raise_server_exceptions=False)

#: The cloud metadata endpoint. Reaching it is the canonical SSRF payoff.
METADATA = "http://169.254.169.254/latest/meta-data/"

#: A public open-redirector. A 302 from here to an internal target is the case
#: a single first-hop ``validate_url`` cannot catch.
REDIRECTOR = "https://redirector.example.com/go"

#: A plausible public page: title, description, h1, and a matching table row so
#: the structure monitor has a selector to find.
PAGE = (
    "<html><head><title>Example Domain</title>"
    '<meta name="description" content="An example page">'
    "</head><body><h1>Example</h1><p>alpha beta gamma</p></body></html>"
)

#: A second public page, the target of the legitimate-redirect test.
FINAL_PAGE = (
    "<html><head><title>Final Domain</title>"
    '<meta name="description" content="Redirect target">'
    "</head><body><h1>Final</h1></body></html>"
)

#: Payload a leaked internal response would carry; asserting on its absence
#: catches a leak even on routes that report the guard's rejection in-body.
LEAK_BODY = "INSTANCE_ID=leaked"

#: One matching and one non-matching selector, so a successful fetch produces
#: a non-trivial result the tests can assert on.
_SELS = [{"name": "h1", "selector": "h1", "type": "css"}]

#: The actor entrypoints under test, with the route each backs and the request
#: body that route expects. ``/v1/seo/track`` and ``/v1/structure/monitor`` call
#: the same actors, so all three SEO/structure fetch paths are covered.
ACTOR_ROUTES: list[tuple[str, str, object]] = [
    ("/v1/seo/analyze", "analyze_seo", METADATA),
    ("/v1/seo/keywords", "get_seo_keyword_insights", METADATA),
    ("/v1/seo/track", "track_seo_changes", METADATA),
    ("/v1/structure/check", "check_selectors", {"url": METADATA, "selectors": _SELS}),
    (
        "/v1/structure/monitor",
        "monitor_page_structure",
        {"url": METADATA, "selectors": _SELS},
    ),
]
ROUTE_IDS = [actor for _, actor, _ in ACTOR_ROUTES]
