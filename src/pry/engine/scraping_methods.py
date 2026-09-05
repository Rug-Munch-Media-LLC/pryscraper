"""Per-method scraping-tier modules for the intelligent fallback chain.

Each tier lives in its own module under ``pry.engine.methods``:

- ``hidden_api``   — ``discover_json_api`` (hidden JSON-API discovery)
- ``session``      — ``PersistentSession`` (cookie warmer / session reuse)
- ``render``       — ``fetch_rendered`` (Playwright/Camoufox render-wait)
- ``feeds``        — ``parse_feed`` / ``discover_feed`` (RSS/Atom)
- ``sitemaps``     — ``parse_sitemap`` / ``discover_sitemap``
- ``graphql``      — ``discover_graphql`` / ``query_graphql``
- ``pagination``   — ``paginated_fetch`` (rate-limit-aware page crawl)
- ``registry``     — ``METHODS`` (tier registry for the fallback chain)
- ``_common``      — shared guarded network/URL helpers + optional browser deps

Every public entry point is guarded (optional browser deps import-lazily)
and never raises: on any failure it returns ``None`` / ``[]`` so the fallback
chain can simply move to the next tier.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

# Backwards-compatible private re-exports (tests import these directly).
from pry.engine.methods.feeds import (  # noqa: F401
    _atom_entries,
    _rss_entries,
    discover_feed,
    parse_feed,
)
from pry.engine.methods.graphql import discover_graphql, query_graphql
from pry.engine.methods.hidden_api import discover_json_api
from pry.engine.methods.pagination import paginated_fetch
from pry.engine.methods.registry import METHODS
from pry.engine.methods.render import fetch_rendered
from pry.engine.methods.session import PersistentSession
from pry.engine.methods.sitemaps import discover_sitemap, parse_sitemap

__all__ = [
    "METHODS",
    "PersistentSession",
    "discover_feed",
    "discover_graphql",
    "discover_json_api",
    "discover_sitemap",
    "fetch_rendered",
    "paginated_fetch",
    "parse_feed",
    "parse_sitemap",
    "query_graphql",
]
