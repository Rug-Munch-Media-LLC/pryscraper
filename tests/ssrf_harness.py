"""Shared harness for the router SSRF regression tests.

The scraping and analysis routers fetch caller-supplied URLs. This module builds
a bare ASGI app containing only the router modules under test, so a test drives a
real route end-to-end and any network attempt is observable.

``respx`` replaces the httpx transport globally while a test runs, so nothing
here (or in the routes under test) opens a socket.

The ``empty_scrape`` fixture lives in ``tests/conftest.py`` — pytest only
discovers fixtures in conftest, not in an imported helper module.

Shared by ``test_router_ssrf_reject.py`` (the attacks that must be blocked),
``test_router_ssrf_allow.py`` (the public scraping that must keep working) and
``test_ai_suggest_ssrf.py`` (``POST /v1/suggest``).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pry.api.exception_handlers import add_error_handlers
from pry.api.routers.ai.analysis import router as analysis_router
from pry.api.routers.scraping.extraction import router as extraction_router
from pry.api.routers.scraping.fetch import guard_get
from pry.api.routers.scraping.parsing import router as parsing_router

app = FastAPI()
app.include_router(extraction_router)
app.include_router(parsing_router)
app.include_router(analysis_router)
# Register the same PryError -> status_code mapping the real app installs. A
# harness app without it turns every guard rejection into a bare 500, which
# would make "a rejected URL returns 4xx" untestable — the assertion would be
# measuring the harness, not the route.
add_error_handlers(app)
client = TestClient(app, raise_server_exceptions=False)

#: A plausible public page (og:image so /v1/thumbnail has something to find).
PAGE = (
    "<html><head><title>Example Domain</title>"
    '<meta property="og:image" content="https://example.com/og.png">'
    "</head><body><h1>Example</h1></body></html>"
)
TABLE_PAGE = "<html><body><table><tr><th>H</th></tr><tr><td>v</td></tr></table></body></html>"

#: Two tables with a <th> header row each, so pandas reads column names from
#: the header rather than synthesising integer column labels.
MULTI_TABLE_PAGE = (
    "<html><body>"
    "<table><thead><tr><th>Region</th><th>Revenue</th></tr></thead>"
    "<tbody><tr><td>EMEA</td><td>10</td></tr></tbody></table>"
    "<table><thead><tr><th>Region</th><th>Revenue</th></tr></thead>"
    "<tbody><tr><td>APAC</td><td>20</td></tr></tbody></table>"
    "</body></html>"
)

#: The cloud metadata endpoint. Reaching it is the canonical SSRF payoff.
METADATA = "http://169.254.169.254/latest/meta-data/"

#: Payload a leaked internal response would carry; asserting on its absence
#: catches a leak even on routes that swallow the guard's rejection.
LEAK_BODY = "INSTANCE_ID=leaked"


async def _guard_get_async(url: str) -> httpx.Response:
    async with httpx.AsyncClient() as c:
        return await guard_get(c, url)


def guard_get_sync(url: str) -> httpx.Response:
    """Call the router fetch helper synchronously over the mocked transport."""
    return asyncio.run(_guard_get_async(url))
