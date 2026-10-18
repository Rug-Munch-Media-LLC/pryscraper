"""Pry — standalone ASGI entrypoint for the MCP HTTP transport.

The MCP surface is normally mounted by the main API at ``/mcp`` (see
``pry.api.app_factory``). This module exposes the same MCP sub-app on its own
so it can be served without the full REST application — e.g.::

    uvicorn pry_mcp.asgi:app --host 0.0.0.0 --port 8006

Why it exists: ``pry.api.mcp_production`` is a stdio-only compatibility shim
(it has no module-level ``app``), so ``uvicorn pry.api.mcp_production:app``
fails with "Attribute 'app' not found". This module is the supported HTTP
entrypoint for the MCP server alone.

Auth: identical to the mounted app — discovery methods (initialize,
tools/list, ping, health) are public; ``tools/call`` requires a Bearer key
(or loopback when keyless in non-prod).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry_mcp.app import create_mcp_app

app = create_mcp_app()

__all__ = ["app"]
