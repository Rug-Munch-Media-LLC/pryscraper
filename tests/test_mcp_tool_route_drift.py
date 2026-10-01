# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Guard against tool->REST route drift in the MCP layer.

``pry_mcp.tool_routes.TOOL_ROUTES`` maps an MCP tool name to the
``(HTTP method, REST path)`` the fallback server proxies to when no local
executor owns the tool. A route that is not in the API contract can never
succeed: the call 404s, the LLM sees an error, and it hallucinates a
workaround around a capability that was never built.

The contract of record is the OpenAPI document produced by
``pry.api.app_factory.app.openapi()["paths"]`` — NOT ``app.routes``, which
reports a handful of mount entries and hides the real router tree.
"""

from __future__ import annotations

import re

import pytest

from pry.api.app_factory import app
from pry_mcp.tool_routes import TOOL_ROUTES

_PATHPARAM = re.compile(r"\{[^/}]+\}")


def _contract_paths() -> set[str]:
    """Return the API contract's paths with path params canonicalised."""
    return {_PATHPARAM.sub("{p}", path.rstrip("/") or "/") for path in app.openapi()["paths"]}


def _normalise(route_path: str) -> str:
    """Canonicalise a TOOL_ROUTES path the same way as the contract."""
    return _PATHPARAM.sub("{p}", route_path.rstrip("/") or "/")


@pytest.fixture(scope="module")
def contract_paths() -> set[str]:
    return _contract_paths()


def test_contract_is_non_trivial() -> None:
    """Guard the guard: an empty contract would make every assertion vacuous."""
    assert len(_contract_paths()) > 100, "OpenAPI contract unexpectedly small"


def test_tool_routes_is_non_empty() -> None:
    assert TOOL_ROUTES, "TOOL_ROUTES is empty — the proxy would never route"


def test_every_tool_route_exists_in_api_contract(contract_paths: set[str]) -> None:
    """Every advertised tool route must resolve to a real API path+method."""
    drifted: list[str] = []
    for tool, (method, path) in sorted(TOOL_ROUTES.items()):
        normalised = _normalise(path)
        spec = app.openapi()["paths"]
        methods = {
            m.lower()
            for candidate in (path, path.rstrip("/"), normalised)
            for m in spec.get(candidate, {})
        }
        if normalised not in contract_paths or method.lower() not in methods:
            drifted.append(f"{tool}: {method} {path}")

    assert not drifted, (
        "TOOL_ROUTES points at routes absent from the API contract. A tool with "
        "no local executor falls through to the REST proxy and 404s. Either add "
        "the endpoint or drop the tool:\n  - " + "\n  - ".join(drifted)
    )
