"""Pry - MCP resource and prompt definitions (facade).

Thin re-export facade. Implementation lives in:

- ``pry_mcp.resources_defs``     — PRY_RESOURCES + DATA_DOMAINS
- ``pry_mcp.resources_prompts``  — PRY_PROMPTS
- ``pry_mcp.resources_handler``  — ResourceHandler

Split from mcp_production.py.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry_mcp.resources_defs import DATA_DOMAINS, PRY_RESOURCES
from pry_mcp.resources_handler import ResourceHandler
from pry_mcp.resources_prompts import PRY_PROMPTS

__all__ = ["DATA_DOMAINS", "PRY_PROMPTS", "PRY_RESOURCES", "ResourceHandler"]
