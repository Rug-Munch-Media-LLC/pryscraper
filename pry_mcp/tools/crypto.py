"""Pry - MCP tool definitions: crypto-market facade and the ``call_crypto_tool`` dispatcher.

Thin re-export facade over the focused crypto modules
(``crypto_security``, ``crypto_launches``, ``crypto_social``).
Split from the former monolithic ``pry_mcp/tools/crypto.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

from .crypto_common import _crypto_module_unavailable
from .crypto_launches import PRY_LAUNCH_TOOLS, handle_cex_listings, handle_token_launches
from .crypto_security import PRY_TOKEN_SECURITY_TOOLS, handle_token_security
from .crypto_social import PRY_KOL_TOOLS, handle_kol_leaderboards

__all__ = [
    "PRY_KOL_TOOLS",
    "PRY_LAUNCH_TOOLS",
    "PRY_TOKEN_SECURITY_TOOLS",
    "PRY_TOOLS",
    "_crypto_module_unavailable",
    "call_crypto_tool",
]

# Market/launch + KOL tool lists; token-security tools live in
# crypto_security and are aggregated separately by the package __init__.
PRY_TOOLS: list[dict[str, Any]] = [
    *PRY_LAUNCH_TOOLS,
    *PRY_KOL_TOOLS,
]

# Re-exports consumed by pry_mcp/tools/__init__.py (kept in __all__ above).


async def call_crypto_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch the crypto-market MCP tools to their ``crypto_market`` handlers.

    The ``crypto_market`` subpackage (``token_launches``, ``cex_listings``,
    ``token_security``, ``kol_leaderboards``) is built in parallel by other
    agents; every import is guarded so this dispatcher degrades gracefully
    (a readable message) if a module has not landed yet. Returns ``None``
    for non-crypto tools so callers fall through to their normal execution
    path (remote executor / REST proxy).
    """
    if name == "pry_token_launches":
        return await handle_token_launches(name, arguments)

    if name == "pry_cex_listings":
        return await handle_cex_listings(name, arguments)

    if name == "pry_token_security":
        return await handle_token_security(name, arguments)

    if name == "pry_kol_leaderboards":
        return await handle_kol_leaderboards(name, arguments)

    return None
