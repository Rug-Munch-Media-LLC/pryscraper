# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Genuinely absent and genuinely broken modules must be told apart.

Split from a single 491-line file to stay under the 200-line structure cap.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest

import pry_mcp.tools as mcp_tools
from pry_mcp.tools._common import (
    _ModuleNotFound,
    resolve_domain_module,
    resolve_domain_package,
)


class TestAbsentModules:
    def test_absent_module_raises_module_not_found(self) -> None:
        module_name = "definitely_not_a_landed_module"
        assert importlib.util.find_spec(f"datasets.sports_data.{module_name}") is None

        with pytest.raises(_ModuleNotFound):
            resolve_domain_module("sports_data", module_name)

    async def test_absent_module_still_returns_unavailable_payload(self) -> None:
        """A not-landed module degrades; it must not raise out of the dispatcher.

        Kills the mutation that lets the resolver's exception escape the
        dispatcher loop, turning a readable MODULE_UNAVAILABLE message into a
        crash for the LLM caller.
        """
        registry = {"pry_never_landed": (("definitely_not_a_landed_module", ("handler",)),)}

        result = await mcp_tools._call_domain_dispatcher(
            "pry_never_landed",
            {},
            "sports_data",
            registry,
            lambda name, arguments: {},
        )

        assert result is not None
        assert result["isError"] is False
        assert "MODULE_UNAVAILABLE" in result["content"][0]["text"]

    def test_absent_package_raises_module_not_found(self) -> None:
        with pytest.raises(_ModuleNotFound):
            resolve_domain_package("definitely_not_a_landed_domain")
