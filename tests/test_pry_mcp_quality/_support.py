# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Shared helpers for the MCP quality audit package."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any

from pry_mcp import make_fallback_server, register_all
from pry_mcp.fallback_server import combined_tool_executor

if TYPE_CHECKING:
    from collections.abc import Iterator

_MISSING = object()


def _module_exists(dotted: str) -> bool:
    """True when ``dotted`` names an importable module."""
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, AttributeError, ValueError):
        return False


@contextmanager
def _patch_module(name: str, module: Any) -> Iterator[None]:
    """Swap ``sys.modules[name]`` for the duration of the test.

    ``module`` may be ``None`` (simulates a module that has not landed yet:
    CPython raises ``ImportError`` for ``from X import Y`` when
    ``sys.modules[X]`` is None) or a fake module object (success path).
    """
    # The dispatchers import domain modules from their REAL namespace,
    # `datasets.<pkg>.<module>` -- no domain module resolves bare. These tests
    # were written against the old resolver, which tried the bare name first,
    # so `sys.modules["crypto_market.token_launches"] = fake` never intercepted
    # anything and the tool executed real code (observed: a live
    # `usda_nass_api_key_missing` warning from datasets.climate_data.agri).
    # Point the patch at the dotted path the resolver will actually import.
    # The namespace is MIXED: some domain modules import bare
    # (crypto_market.token_launches), the rest only under `datasets.`. The
    # resolver tries an ordered candidate list, so a patch that covers only one
    # of the two is a no-op for the other -- which is how these tests ended up
    # executing real code. Patch every candidate that actually exists.
    candidates = [name]
    prefixed = f"datasets.{name}"
    if prefixed not in candidates:
        candidates.append(prefixed)
    live = [c for c in candidates if _module_exists(c)] or [name]

    saved: list[tuple[str, Any]] = []
    for cand in live:
        parent = cand.rsplit(".", 1)[0]
        if "." in cand:
            with suppress(ImportError):
                __import__(parent)
        saved.append((cand, sys.modules.get(cand, _MISSING)))
        sys.modules[cand] = module
    try:
        yield
    finally:
        for cand, original in saved:
            if original is _MISSING:
                sys.modules.pop(cand, None)
            else:
                sys.modules[cand] = original


def _fake_module(**attrs: Any) -> types.ModuleType:
    """Build a minimal module object exposing async callables (AsyncMock)."""
    module = types.ModuleType("fake")
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _server() -> Any:
    """A fully registered fallback server with the combined tool executor."""
    srv = make_fallback_server(
        base_url="http://mcp-test.invalid",
        tool_executor=combined_tool_executor,
    )
    register_all(srv)
    return srv


async def _call(srv: Any, name: str, args: dict[str, Any], req_id: int = 100) -> dict[str, Any]:
    """Issue a ``tools/call`` JSON-RPC request and return the response."""
    resp = await srv.handle_request(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    assert resp is not None
    return resp
