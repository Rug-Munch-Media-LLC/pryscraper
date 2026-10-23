"""Pry - MCP resources, prompts and completions (facade).

Replaces the former ``pry_mcp/resources.py`` module, so the ``pry_mcp.resources``
import path and its public names are unchanged. Implementation lives in:

- ``pry_mcp.resources_defs``        — ``PRY_RESOURCES`` + ``DATA_DOMAINS``
- ``pry_mcp.resources_prompts``     — ``PRY_PROMPTS`` definitions
- ``pry_mcp.resources.domains``     — ``pry://`` resource bodies
- ``pry_mcp.resources.prompts``     — prompt message bodies
- ``pry_mcp.resources.completions`` — argument completion
- ``pry_mcp.resources_handler``     — ``ResourceHandler`` facade
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from pry_mcp.resources.completions import completion_values
from pry_mcp.resources.domains import resource_text
from pry_mcp.resources.prompts import prompt_messages
from pry_mcp.resources_defs import DATA_DOMAINS, PRY_RESOURCES
from pry_mcp.resources_handler import ResourceHandler
from pry_mcp.resources_prompts import PRY_PROMPTS

__all__ = [
    "DATA_DOMAINS",
    "PRY_PROMPTS",
    "PRY_RESOURCES",
    "ResourceHandler",
    "completion_values",
    "prompt_messages",
    "resource_text",
]
