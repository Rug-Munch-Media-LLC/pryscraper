"""Pry v3 — Full-stack web intelligence API.
Scrape + Crawl + Automate + Parse + Extract + MCP
Self-hosted, free, better than Firecrawl.

Thin re-export facade — implementation lives in focused sibling modules:

- ``app_factory``       — FastAPI app assembly, middleware, spec endpoints
- ``router_registry``   — router imports + ``register_routers()``
- ``lifecycle``         — logging setup + ``lifespan()`` startup/shutdown
- ``exception_handlers``— RFC 7807 error handlers
- ``mcp_server``        — MCP sub-app mounted at ``/mcp``
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from pry.api.app_factory import (
    app,
    get_metrics,
    readyz,
    supported_payment_kinds,
)
from pry.api.exception_handlers import add_error_handlers
from pry.api.lifecycle import lifespan, logger
from pry.api.mcp_server import (  # noqa: F401  (_get_mcp_server re-exported; tests patch it)
    _get_mcp_server,
    mcp_app,
)
from pry.core.middleware import (
    PryHttpMiddleware,
    is_loopback_client,
    request_authorized,
)

__all__ = [
    "PryHttpMiddleware",
    "add_error_handlers",
    "app",
    "get_metrics",
    "is_loopback_client",
    "lifespan",
    "logger",
    "mcp_app",
    "readyz",
    "request_authorized",
    "supported_payment_kinds",
]
