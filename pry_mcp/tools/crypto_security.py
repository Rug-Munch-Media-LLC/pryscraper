"""Pry - MCP tool definitions: token security tools.

Split from the former ``pry_mcp/tools/crypto.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any

from ._common import _missing_arg
from .crypto_common import _crypto_module_unavailable, _json_result

logger = logging.getLogger(__name__)

PRY_TOKEN_SECURITY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_token_security",
        "description": (
            "Run a security scan on a crypto token by chain and contract/mint address — "
            "checking for honeypots, hidden mints, ownership concentration, LP lock, and "
            "other rug-pull risk signals. "
            "Use before investing in or reporting on an unfamiliar token, e.g. 'scan "
            "So11111111111111111111111111111111111111112 on solana'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chain": {
                    "type": "string",
                    "description": (
                        "Blockchain the token lives on (e.g., 'solana', 'ethereum', 'base')"
                    ),
                },
                "address": {
                    "type": "string",
                    "description": (
                        "Token contract or mint address, e.g. "
                        "'So11111111111111111111111111111111111111112'"
                    ),
                },
            },
            "required": ["chain", "address"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "chain": {"type": "string"},
                        "address": {"type": "string"},
                        "risk_score": {"type": "number"},
                        "risk_level": {"type": "string"},
                        "verdict": {"type": "string"},
                        "flags": {"type": "array", "items": {"type": "string"}},
                        "checks": {"type": "object"},
                        "source": {"type": "string"},
                    },
                },
            },
            "required": ["success"],
        },
    }
]


async def handle_token_security(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch ``pry_token_security`` to its ``crypto_market`` handler."""
    chain = arguments.get("chain", "")
    address = arguments.get("address", "")
    if not chain or not address:
        return _missing_arg(name, "chain and address")
    try:
        from crypto_market.token_security import scan_token
    except ImportError as e:
        logger.warning(
            "suppressed %s in handle_token_security (crypto_security.py:91): %s",
            "ImportError",
            e,
        )
        return _crypto_module_unavailable(name)
    scan_data = await scan_token(chain, address)
    return _json_result(scan_data)
