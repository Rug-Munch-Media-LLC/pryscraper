"""Pry - shared helpers for the crypto-market MCP tool modules.

Split from the former ``pry_mcp/tools/crypto.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
from typing import Any


def _crypto_module_unavailable(tool_name: str) -> dict[str, Any]:
    """MCP content dict for a crypto tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the crypto_market module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
                ),
            }
        ],
        "isError": False,
    }


def _json_result(data: Any) -> dict[str, Any]:
    """Wrap a handler payload in the standard MCP text-content envelope."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"success": True, "data": data}, indent=2),
            }
        ],
        "isError": False,
    }
