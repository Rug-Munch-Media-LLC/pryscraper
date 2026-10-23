"""Pry - MCP resource / prompt / completion facade.

``ResourceHandler`` holds the live registries and delegates the work:

- ``pry_mcp.resources.domains``     — ``pry://`` resource bodies
- ``pry_mcp.resources.prompts``     — prompt message bodies
- ``pry_mcp.resources.completions`` — argument completion

Resource and prompt names are unchanged; the private helpers are kept as
delegators so existing callers and tests keep working.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pry_mcp.resources.completions import completion_values
from pry_mcp.resources.domains import resource_text
from pry_mcp.resources.prompts import prompt_messages


class ResourceHandler:
    """Resource / prompt / completion handlers for the MCP server.

    Holds the live ``resources`` / ``prompts`` registries (and ``tools`` for the
    ``pry://stats`` resource) and implements the read/prompt/completion
    protocol methods.
    """

    def __init__(
        self,
        resources: dict[str, dict[str, Any]],
        prompts: dict[str, dict[str, Any]],
        tools: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.resources = resources
        self.prompts = prompts
        self.tools = tools if tools is not None else {}

    def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource. Returns proper MCP-compliant response."""
        if uri not in self.resources:
            return {"error": {"code": -32602, "message": f"Resource not found: {uri}"}}
        res = self.resources[uri]
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": res.get("mimeType", "text/plain"),
                    "text": self._resource_text(uri),
                }
            ],
        }

    def _resource_text(self, uri: str) -> str:
        """Generate resource contents without external I/O."""
        return resource_text(uri, self.resources, self.prompts, self.tools)

    def get_prompt(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Get a prompt. Returns proper MCP-compliant response."""
        if name not in self.prompts:
            return {"error": {"code": -32602, "message": f"Prompt not found: {name}"}}
        prompt = self.prompts[name]
        return {
            "description": prompt.get("description", ""),
            "messages": self._prompt_messages(name, arguments),
        }

    def _prompt_messages(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Build real prompt messages for named prompts."""
        title = self.prompts[name].get("title", name)
        return prompt_messages(name, arguments, title)

    def complete(self, ref: dict[str, Any], argument: dict[str, Any]) -> dict[str, Any]:
        """Provide argument completion suggestions."""
        return {"values": completion_values(ref, argument)}
