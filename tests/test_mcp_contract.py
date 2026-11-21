# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP tool contract: ADVERTISED surface vs IMPLEMENTED dispatch.

`PRY_TOOLS` is what agents are told exists. This module pins the contract
between that advertised list and the code that can actually answer a call:

- (a) every advertised tool is *reachable*: the live dispatch chain claims it
  (a local dispatcher or the REST route table serves it), so a `tools/call`
  can never end at the server's `TOOL_NOT_WIRED` branch; and the advertised
  list matches the surface `register_all()` puts on the wire.
- (b) every advertised `inputSchema` is a valid JSON-Schema object
  (`type: object` + a `properties` object).
- (c) an unknown tool returns a clean, structured error - never a traceback.
- (d) a high-risk tool called with missing required args is rejected with a
  structured validation error.

All checks are in-process. The reachability probe forces every `datasets.*`
domain module import to fail, so no domain handler can reach the network; a
tool is "claimed" when the chain returns a result (e.g. MODULE_UNAVAILABLE)
rather than raising `_ToolNotHandled` (which the server turns into
`TOOL_NOT_WIRED`).
"""

from __future__ import annotations

import builtins
import json
import socket
from typing import Any

import pytest

from pry_mcp import register_all
from pry_mcp.fallback_server import make_fallback_server
from pry_mcp.tool_registry import _ToolNotHandled, combined_tool_executor
from pry_mcp.tool_routes import TOOL_ROUTES
from pry_mcp.tools import PRY_TOOL_NAMES, PRY_TOOLS

# A representative slice: one scraping tool, one billing tool, one crypto
# tool, one locally-dispatched data tool, one REST-routed data tool. Kept
# small on purpose - the module-level guards below already cover all 99.
_SAMPLE_TOOLS = (
    "pry_scrape",
    "pry_balance",
    "pry_token_security",
    "pry_amazon_product",
    "pry_odds",
)


def _server() -> Any:
    """A fully registered fallback server backed by the real dispatch chain."""
    srv = make_fallback_server(
        base_url="http://mcp-contract.invalid",
        tool_executor=combined_tool_executor,
    )
    register_all(srv)
    return srv


# ── (a) advertised == wire surface, and every advertised tool is reachable ──


def test_advertised_surface_is_registered_on_the_wire() -> None:
    """register_all must project exactly the advertised tool names."""
    srv = _server()
    assert set(srv.tools) == set(PRY_TOOL_NAMES)


@pytest.mark.parametrize("tool_name", sorted(PRY_TOOL_NAMES))
async def test_every_advertised_tool_is_reachable(tool_name: str, monkeypatch) -> None:
    """No advertised tool may dead-end at the server's TOOL_NOT_WIRED branch.

    A tool is reachable when the chain *claims* it: it returns a result or a
    structured error instead of raising ``_ToolNotHandled``. Domain modules are
    blocked so a claim can never turn into a live HTTP/DNS call.
    """
    real_import = builtins.__import__

    def _block_datasets(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "datasets" or name.startswith("datasets."):
            raise ModuleNotFoundError(f"blocked {name}", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_datasets)

    # Blocking the `datasets` module was a guess at where the network call lives,
    # and it was the wrong guess: `pry_arbitrage` reached out over a real socket
    # and hung in selector.poll() until the runner was killed, which is what made
    # the whole suite take ~3 hours instead of ~3 minutes.
    #
    # The invariant the docstring states is "no domain handler can reach the
    # network". Enforce THAT, at the one place every outbound call must pass
    # through, instead of enumerating module names and hoping the list is
    # complete. connect_ex covers httpx, urllib, aiohttp, raw sockets and
    # anything else that dials out.
    def _no_connect(self: Any, *_a: Any, **_kw: Any) -> Any:
        import errno

        raise OSError(errno.ENETUNREACH, "network disabled in the tool-contract probe")

    def _no_connect_ex(self: Any, *_a: Any, **_kw: Any) -> int:
        # `connect_ex` is DOCUMENTED to return an errno instead of raising, and
        # callers branch on the value (`if sock.connect_ex(...) != 0:`). Making
        # it raise broke that contract: an exception inside a retry loop turned
        # a fast "refused" into a re-attempt cycle that never terminated, which
        # is what made the full suite stall here. Return the errno the contract
        # promises, so a probed tool fails immediately the way it would on a
        # genuinely unreachable network.
        import errno

        return errno.ENETUNREACH

    monkeypatch.setattr(socket.socket, "connect", _no_connect, raising=False)
    monkeypatch.setattr(socket.socket, "connect_ex", _no_connect_ex, raising=False)
    try:
        await combined_tool_executor(tool_name, {})
    except _ToolNotHandled:
        if tool_name in TOOL_ROUTES:
            return  # falls through to the REST proxy - still implemented
        pytest.fail(
            f"{tool_name} is advertised but neither dispatched locally nor "
            f"present in TOOL_ROUTES - a tools/call ends at TOOL_NOT_WIRED"
        )


def test_advertised_names_are_unique_and_well_formed() -> None:
    """(a) The advertised surface is a clean, unambiguous set of tool names."""
    names = [t["name"] for t in PRY_TOOLS]
    assert len(names) == len(set(names)), "duplicate advertised tool names"
    # 100 of 101 tools are `pry_*`. `dextools_search` is the one deliberate
    # exception: it is the published name for our own Dextools store and is
    # already referenced from src/pry/misc/cli_dextools.py and the quality
    # tables, so renaming it is an API break for a naming convention that is
    # not written down anywhere. Assert the rule WITH its exception rather than
    # failing on reality, and keep the set explicit so a third exception has to
    # be argued for here instead of slipping in.
    non_prefixed = {"dextools_search"}
    offenders = [n for n in names if not n.startswith("pry_") and n not in non_prefixed]
    assert not offenders, f"non-pry tools advertised outside the allowance: {offenders}"


# ── (b) schemas are valid JSON-Schema objects ───────────────────────────────


@pytest.mark.parametrize("tool_name", sorted(PRY_TOOL_NAMES))
def test_input_schema_is_valid_object_schema(tool_name: str) -> None:
    tool = next(t for t in PRY_TOOLS if t["name"] == tool_name)
    schema = tool.get("inputSchema")
    assert isinstance(schema, dict), f"{tool_name}: inputSchema is not a dict"
    assert schema.get("type") == "object", f"{tool_name}: type != object"
    props = schema.get("properties")
    assert isinstance(props, dict), f"{tool_name}: properties is not an object"
    for req in schema.get("required", []):
        assert req in props, f"{tool_name}: required '{req}' missing from properties"


# ── (c) unknown tool -> clean structured error, no traceback ────────────────


async def test_unknown_tool_returns_clean_error() -> None:
    srv = _server()
    result = await srv.call_tool("pry_definitely_not_a_real_tool", {})
    assert "error" in result, result
    err = result["error"]
    assert err.get("code") == -32602
    assert "Unknown tool" in err.get("message", "")
    # A traceback would have leaked a raw exception string instead.
    assert "Traceback" not in json.dumps(result)


# ── (d) missing required args -> structured validation error ────────────────


async def test_missing_required_arg_is_a_validation_error() -> None:
    srv = _server()
    result = await srv.call_tool("pry_scrape", {})  # 'url' required
    assert result.get("isError") is True, result
    err = result["error"]
    assert err.get("code") == "invalid_args"
    assert "missing required argument 'url'" in err.get("message", "")
    assert "Traceback" not in json.dumps(result)


@pytest.mark.parametrize("tool_name", sorted(_SAMPLE_TOOLS))
async def test_sample_tools_stay_structured_when_called_empty(tool_name: str) -> None:
    """Representative tools answer a bare call with structure, never a crash."""
    srv = _server()
    result = await srv.call_tool(tool_name, {})
    assert isinstance(result, dict)
    assert "content" in result or "error" in result, result
    assert "Traceback" not in json.dumps(result)
