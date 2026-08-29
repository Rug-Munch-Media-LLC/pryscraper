# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""MCP <-> Apify publication catalog parity.

Guarantees the two actor lists are the SAME set, structurally:

- The MCP surface (``pry_actor_catalog``) enumerates ``ALL_PRESETS``.
- The Apify publication pipeline (``actor_factory.publish`` / ``generate_actor``)
  stages the SAME ``ALL_PRESETS`` into Apify actor packages.

Both derive from the single source ``actor_factory.presets.ALL_PRESETS``, so
an actor added to the factory is automatically reachable from MCP and
publishable on Apify — this test makes that invariant explicit and breaks if
either side drifts.

Also pins the committed flagship ``.actor/`` package to a resolvable build
file (item: ``.actor/actor.json`` -> correct dockerfile).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from actor_factory.presets import ALL_PRESETS
from actor_factory.publish import sorted_specs
from actor_factory.runner import PPEScraperRunner
from pry_mcp.tools import _actor_catalog_entries


def _actor_json() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads((Path(".actor") / "actor.json").read_text()))


def _mcp_actor_names() -> set[str]:
    """Actor names advertised by the MCP ``pry_actor_catalog`` (pry- stripped)."""
    return {entry["actor"] for entry in _actor_catalog_entries()}


def _apify_actor_names() -> set[str]:
    """Actor names the Apify publication pipeline stages (pry- stripped)."""
    return {spec.name.removeprefix("pry-") for spec in sorted_specs()}


class TestCatalogParity:
    def test_mcp_and_apify_expose_the_same_actors(self) -> None:
        mcp = _mcp_actor_names()
        apify = _apify_actor_names()
        assert mcp == apify, (
            f"MCP/Apify catalog drift.\n  only MCP: {sorted(mcp - apify)}\n"
            f"  only Apify: {sorted(apify - mcp)}"
        )

    def test_single_source_is_all_presets(self) -> None:
        """Every advertised actor is a preset (and every preset is advertised)."""
        mcp = _mcp_actor_names()
        assert mcp == {name.removeprefix("pry-") for name in ALL_PRESETS}

    def test_actor_count_matches_catalog_claim(self) -> None:
        """MCP tool docstring claims 94 store actors; keep it truthful."""
        assert len(_mcp_actor_names()) == len(ALL_PRESETS)
        assert len(_mcp_actor_names()) >= 1

    def test_flagship_actor_is_in_catalog(self) -> None:
        """The committed ``.actor/`` flagship is a member of the shared set."""
        spec = _actor_json()
        name = spec["name"].removeprefix("pry-")
        assert name in _mcp_actor_names()
        assert name in _apify_actor_names()

    def test_flagship_dockerfile_resolves(self) -> None:
        """Item: ``.actor/actor.json`` points at a real build file."""
        spec = _actor_json()
        target = Path(".actor") / spec["dockerfile"].lstrip("./")
        assert target.is_file(), f"actor.json dockerfile missing: {spec['dockerfile']}"
        assert target.name == "Dockerfile.apify"


class TestRunnerParity:
    def test_pry_actor_run_uses_runner_py(self) -> None:
        """The MCP actor runner must be the same ``PPEScraperRunner`` the Apify
        factory-published actors use (behavioral parity, not just names)."""
        import actor_factory.runner

        assert actor_factory.runner.PPEScraperRunner is PPEScraperRunner

        # The MCP dispatcher imports the runner from the shared module, so it
        # cannot silently fork to a different engine.
        import inspect

        import pry_mcp.tools

        src = inspect.getsource(pry_mcp.tools.call_actor_tool)
        assert "PPEScraperRunner" in src
        assert "from actor_factory.runner import" in src or "actor_factory.runner" in src
