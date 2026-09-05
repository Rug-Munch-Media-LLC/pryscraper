"""Tier registry for the fallback chain — describes each method and when to use it."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pry.engine.methods.feeds import parse_feed
from pry.engine.methods.graphql import discover_graphql
from pry.engine.methods.hidden_api import discover_json_api
from pry.engine.methods.pagination import paginated_fetch
from pry.engine.methods.render import fetch_rendered
from pry.engine.methods.session import PersistentSession
from pry.engine.methods.sitemaps import parse_sitemap

METHODS: dict[str, dict[str, Any]] = {
    "hidden_api_discovery": {
        "name": "Hidden-API discovery",
        "callable": discover_json_api,
        "sync": True,
        "signature": "discover_json_api(page_url, html) -> list[str]",
        "when": (
            "Use after a page fetch succeeds but returns a JS shell — scan "
            "the HTML for the JSON endpoints the frontend calls, then fetch "
            "and JSON-parse each candidate instead of scraping rendered HTML."
        ),
        "cost": "free",
        "notes": (
            "Returns absolute candidate URLs (deduped). Fetch each with a "
            "PersistentSession; re-scan fetched JS bundles for deeper endpoints."
        ),
    },
    "persistent_session": {
        "name": "Session persistence / cookie warmer",
        "callable": PersistentSession,
        "sync": False,
        "signature": "PersistentSession(home_url).fetch(url, params) -> httpx.Response | None",
        "when": (
            "Use for JSON APIs that require a session cookie set by a prior "
            "homepage visit (sportsbook odds, retail catalog APIs) — warm the "
            "homepage once, then reuse the cookie jar across calls."
        ),
        "cost": "free",
        "notes": "Homepage derived from the first fetch URL when not configured.",
    },
    "render_wait": {
        "name": "Render-wait (JS SPA)",
        "callable": fetch_rendered,
        "sync": False,
        "signature": (
            "fetch_rendered(url, wait_ms=3000, *, selector='', proxy='', "
            "collect_json=False) -> str | None"
        ),
        "when": (
            "Use when content is rendered client-side with no JSON API, or "
            "when a JS challenge needs a real browser (network-idle wait). "
            "collect_json=True returns intercepted JSON responses as a string."
        ),
        "cost": "browser",
        "notes": "Playwright by default; Camoufox when prefer='camoufox' or the package is present.",
    },
    "feed_parsing": {
        "name": "RSS/Atom feed parsing",
        "callable": parse_feed,
        "sync": True,
        "signature": "parse_feed(url) -> list[dict] (+ discover_feed(page_url, html) -> str | None)",
        "when": (
            "Use when a site publishes an RSS/Atom feed (news, blogs, podcast "
            "shows, changelogs): discover_feed finds the <link rel=alternate> "
            "from a page, parse_feed returns structured entries."
        ),
        "cost": "free",
        "notes": "Stdlib xml.etree — no extra deps. Entries carry title/link/summary/published.",
    },
    "sitemap_discovery": {
        "name": "Sitemap-driven discovery",
        "callable": parse_sitemap,
        "sync": True,
        "signature": "parse_sitemap(url) -> list[str] (+ discover_sitemap(domain) -> str | None)",
        "when": (
            "Use to enumerate all URLs of a site: discover_sitemap finds the "
            "sitemap via robots.txt (or /sitemap.xml), parse_sitemap flattens "
            "urlset and sitemap-index XML into URLs."
        ),
        "cost": "free",
        "notes": "Bounded recursion (depth 2, max 20 fetches) and cycle-safe.",
    },
    "graphql_discovery": {
        "name": "GraphQL endpoint discovery",
        "callable": discover_graphql,
        "sync": True,
        "signature": (
            "discover_graphql(page_url, html) -> list[str] "
            "(+ query_graphql(endpoint, query, variables) -> dict | None)"
        ),
        "when": (
            "Use when a site is powered by GraphQL (Apollo / Hasura): "
            "discover_graphql scans HTML for endpoint candidates, "
            "query_graphql POSTs a query JSON-style."
        ),
        "cost": "free",
        "notes": "POST body: {'query': ..., 'variables': {...}}; SSRF-validated; never raises.",
    },
    "paginated_crawl": {
        "name": "Rate-limit-aware paginated crawl",
        "callable": paginated_fetch,
        "sync": True,
        "signature": (
            "paginated_fetch(url, page_param='page', max_pages=5, per_page_delay=0.5) -> list[dict]"
        ),
        "when": (
            "Use for JSON list APIs served in pages (?page=N): fetches pages "
            "with a courtesy delay between requests and stops on an empty page."
        ),
        "cost": "free",
        "notes": "Unwraps results/data/items keys from dict payloads; never raises.",
    },
}

__all__ = ["METHODS"]
