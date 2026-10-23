"""MCP sub-app — spec-compliant MCP server mounted at ``/mcp``.

Split out of api.py (god-file split, 2026-09).

The lambda defers the ``_get_mcp_server`` lookup to request time through the
``pry.api.api`` facade, so tests that patch ``pry.api.api._get_mcp_server``
keep working.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import os
from typing import Any

from pry.core.settings import settings
from pry_mcp import make_fallback_server, register_all
from pry_mcp.app import create_mcp_app

_mcp_server_instance: Any | None = None


def _get_mcp_server() -> Any:
    """Lazy-initialize the spec-compliant MCP server."""
    global _mcp_server_instance
    if _mcp_server_instance is None:
        from pry_mcp.fallback_server import combined_tool_executor

        # tool_executor is REQUIRED for local domain dispatch: without it the
        # server falls through to the REST proxy for every tool, and the
        # actor tools (pry_actor_catalog/pry_actor_run — pure-local, no REST
        # route) return TOOL_NOT_WIRED. combined_tool_executor chains the
        # actor + crypto + marketplace + 21 domain dispatchers and raises
        # _ToolNotHandled for anything REST-wired, which then proxies.
        _mcp_server_instance = make_fallback_server(
            base_url=os.getenv("PRY_URL") or f"http://localhost:{settings.port}",
            tool_executor=combined_tool_executor,
        )
        register_all(_mcp_server_instance)
    return _mcp_server_instance


def _resolve_server() -> Any:
    """Resolve through the api facade so ``patch("pry.api.api._get_mcp_server")`` works."""
    import pry.api.api as _api

    return getattr(_api, "_get_mcp_server", _get_mcp_server)()


# Built by pry_mcp.app.create_mcp_app(); mounted on /mcp so that streaming SSE
# endpoints bypass the main app's BaseHTTPMiddleware (which buffers response
# bodies and breaks SSE).
mcp_app = create_mcp_app(get_server=_resolve_server)
