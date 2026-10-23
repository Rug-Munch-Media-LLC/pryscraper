"""Pry - MCP tool error envelopes, the fall-through sentinel, and the handler
exception tuple.

Both transports (JSON-RPC fallback and SDK) return the same shapes, so they
live in one file instead of being rebuilt in every executor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
from typing import Any

import httpx

TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"

# What a local handler may legitimately raise: a data-shape surprise inside an
# adapter (AttributeError/KeyError/IndexError/TypeError/ValueError), a network
# or timeout failure from the upstream it wraps (OSError/httpx.HTTPError), a
# parse/registry failure reported as RuntimeError, or a domain package that
# will not import (ImportError). Anything outside this tuple escapes to the
# registry's protocol boundary, which returns a structured error instead of
# dropping the MCP connection.
HANDLER_ERRORS = (
    AttributeError,
    ImportError,
    KeyError,
    LookupError,
    TypeError,
    ValueError,
    OSError,
    RuntimeError,
    httpx.HTTPError,
)


class ToolNotHandled(Exception):
    """Raised by a local tool executor to fall through to the REST proxy."""


def structured_error(tool_name: str, code: str, message: str) -> dict[str, Any]:
    """Error result for both transports: ``error`` + MCP ``content``/``isError``."""
    return {
        "error": {"code": code, "message": message},
        "content": [{"type": "text", "text": json.dumps({"error": message, "code": code})}],
        "isError": True,
    }


def handler_failure(tool_name: str, exc: BaseException) -> dict[str, Any]:
    """MCP content envelope for a local handler that raised.

    The envelope is protocol data, not a crash: the client gets a readable
    ``TOOL_EXECUTION_FAILED`` payload and the server keeps serving.
    """
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"error": f"Tool {tool_name} failed: {exc}", "code": TOOL_EXECUTION_FAILED}
                ),
            }
        ],
        "isError": True,
    }


# Back-compat alias: the name was private before the split, and both the
# registry and its tests still refer to it.
_structured_error = structured_error
