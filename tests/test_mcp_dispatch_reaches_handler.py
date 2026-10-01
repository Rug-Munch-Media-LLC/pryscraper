# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""End-to-end: the repaired tools now reach their handler.

Split from a single 491-line file to stay under the 200-line structure cap.
"""

from __future__ import annotations

import pry_mcp.tools as mcp_tools


class TestDispatcherReachesHandler:
    async def test_pry_restaurant_reaches_handler(self) -> None:
        """``pry_restaurant`` returned MODULE_UNAVAILABLE; it must now work.

        Kills the mutation that reintroduces the bare import in
        ``_call_domain_dispatcher`` — this is the exact tool from the defect
        report (``food_data.restaurants``).
        """
        result = await mcp_tools.call_food_tool(
            "pry_restaurant", {"name": "Katz's Delicatessen", "location": "New York"}
        )

        assert result is not None
        text = result["content"][0]["text"]
        assert "MODULE_UNAVAILABLE" not in text
        assert result["isError"] is False
        assert '"success": true' in text

    async def test_pry_grocery_reaches_handler(self) -> None:
        """Sibling food tool in the same broken registry.

        Kills a mutation that fixes only the module named in the defect report
        (``restaurants``) and leaves the sibling unresolvable. The tool also
        asserts the resolved handler was *called with a valid signature*: the
        MCP argument is ``zip`` while the landed handler takes ``zip_code``, so
        a resolver that finds the module but builds the wrong kwargs still
        fails here (as a TypeError out of the dispatcher) instead of passing.
        """
        result = await mcp_tools.call_food_tool("pry_grocery", {"query": "milk", "zip": "78701"})

        assert result is not None
        assert "MODULE_UNAVAILABLE" not in result["content"][0]["text"]
