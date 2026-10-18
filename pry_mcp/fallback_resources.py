"""Pry - MCP fallback server: resources, prompts, completions.

Owns the resource/prompt registry, subscription bookkeeping and the
``resources/*``, ``prompts/*`` and ``completion/complete`` methods. The
heavy lifting stays in ``pry_mcp.resources_handler.ResourceHandler``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from pry_mcp.fallback_protocol import RpcError
from pry_mcp.resources import ResourceHandler


class ResourceMixin:
    """Resource / prompt / completion surface."""

    tools: dict[str, dict[str, Any]]
    resources: dict[str, dict[str, Any]]
    prompts: dict[str, dict[str, Any]]
    _resource_subscribers: dict[str, set[str]]
    _rh: ResourceHandler

    def _init_resources(self) -> None:
        self.resources = {}
        self.prompts = {}
        # uri -> set of subscriber session/client ids
        self._resource_subscribers = {}
        self._rh = ResourceHandler(self.resources, self.prompts, self.tools)

    def register_resource(self, uri: str, definition: dict[str, Any]) -> None:
        self.resources[uri] = definition

    def register_prompt(self, name: str, definition: dict[str, Any]) -> None:
        self.prompts[name] = definition

    def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource. Returns proper MCP-compliant response."""
        return self._rh.read_resource(uri)

    def _resource_text(self, uri: str) -> str:
        """Generate resource contents without external I/O."""
        return self._rh._resource_text(uri)

    def get_prompt(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Get a prompt. Returns proper MCP-compliant response."""
        return self._rh.get_prompt(name, arguments)

    def _prompt_messages(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Build real prompt messages for named prompts."""
        return self._rh._prompt_messages(name, arguments)

    def complete(self, ref: dict[str, Any], argument: dict[str, Any]) -> dict[str, Any]:
        """Provide argument completion suggestions."""
        return self._rh.complete(ref, argument)

    def subscribe_resource(self, uri: str, subscriber_id: str = "default") -> bool:
        """Subscribe a client to updates for a resource URI."""
        if uri not in self.resources:
            return False
        self._resource_subscribers.setdefault(uri, set()).add(subscriber_id)
        return True

    def unsubscribe_resource(self, uri: str, subscriber_id: str = "default") -> bool:
        """Unsubscribe a client from updates for a resource URI."""
        subscribers = self._resource_subscribers.get(uri)
        if subscribers is None:
            return False
        subscribers.discard(subscriber_id)
        if not subscribers:
            del self._resource_subscribers[uri]
        return True

    # ------------------------------------------------------------ JSON-RPC

    async def _rpc_resources_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"resources": list(self.resources.values())}

    async def _rpc_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        read_result = self.read_resource(params.get("uri", ""))
        if "error" in read_result:
            error = read_result["error"]
            raise RpcError(error["code"], error["message"])
        return read_result

    async def _rpc_resources_subscribe(self, params: dict[str, Any]) -> dict[str, Any]:
        ok = self.subscribe_resource(params.get("uri", ""))
        return {"subscribed": ok}

    async def _rpc_resources_unsubscribe(self, params: dict[str, Any]) -> dict[str, Any]:
        ok = self.unsubscribe_resource(params.get("uri", ""))
        return {"unsubscribed": ok}

    async def _rpc_prompts_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"prompts": list(self.prompts.values())}

    async def _rpc_prompts_get(self, params: dict[str, Any]) -> dict[str, Any]:
        prompt_result = self.get_prompt(params.get("name", ""), params.get("arguments", {}))
        if "error" in prompt_result:
            error = prompt_result["error"]
            raise RpcError(error["code"], error["message"])
        return prompt_result

    async def _rpc_completion_complete(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.complete(params.get("ref", {}), params.get("argument", {}))
