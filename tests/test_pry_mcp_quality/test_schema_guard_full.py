# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Layer 4c: the phantom-field guard covers the whole surface, not 20 tools.

``test_schema_alignment`` pins the 2026-10-23 fix through a hand-written
``EMITTER_MODULES`` table. That table is why the other 79 tools drifted: a tool
that is not on the list cannot fail, so a declared field nobody emits survives
review indefinitely. These tests hold the surface itself — the emitter for each
tool is derived from its dispatch source (``_emitter_resolve``), so a new tool
is guarded the moment it ships.

A tool that resolves to nothing is not silently skipped: it must be named in
``UNTRACKED`` with a reason. That is the one place a human decides, and a test
fails if the decision is missing.
"""

from __future__ import annotations

import pytest

from pry_mcp import PRY_TOOLS

from ._emitter_resolve import UNTRACKED, declared_data_fields, tool_emitter_modules
from ._emitter_scan import emitted_literals
from ._schema_alignment_tables import ALIGNED_TOOL_NAMES

TOOLS = {tool["name"]: tool for tool in PRY_TOOLS}
RESOLVED = tool_emitter_modules()

#: The guard must never shrink below the surface it was proven on
#: (2026-10-24: 86 of 99 tools resolve, 74 declare a checkable ``data`` shape).
MIN_RESOLVED = 80


def _declared(name: str) -> set[str]:
    return declared_data_fields(TOOLS[name].get("outputSchema") or {})


def _emitted(name: str) -> set[str]:
    literals: set[str] = set()
    for module in RESOLVED[name]:
        literals |= emitted_literals(module)
    return literals


_CHECKABLE = sorted(name for name in TOOLS if name in RESOLVED and _declared(name))


class TestGuardCoversEveryTool:
    """Coverage is asserted, not assumed."""

    def test_every_declaring_tool_resolves_or_is_declared_untracked(self) -> None:
        unguarded = sorted(name for name in TOOLS if _declared(name) and name not in RESOLVED)
        unexplained = [name for name in unguarded if name not in UNTRACKED]
        assert not unexplained, (
            f"{unexplained}: declare a data shape but resolve to no emitter. Wire the "
            "dispatch in _emitter_resolve or add the tool to UNTRACKED with the reason."
        )

    def test_untracked_names_real_tools(self) -> None:
        assert not sorted(set(UNTRACKED) - set(TOOLS)), "UNTRACKED lists a tool that is gone"

    def test_untracked_overlaps_nothing_resolved(self) -> None:
        stale = sorted(set(UNTRACKED) & set(RESOLVED))
        assert not stale, f"{stale}: marked UNTRACKED but the emitter resolves — drop the entry"

    def test_untracked_states_a_reason(self) -> None:
        vague = sorted(tool for tool, why in UNTRACKED.items() if len(why.split()) < 4)
        assert not vague, f"{vague}: UNTRACKED needs a reason a reviewer can check"

    def test_coverage_never_shrinks(self) -> None:
        assert len(RESOLVED) >= MIN_RESOLVED, (
            f"only {len(RESOLVED)} tools resolve (floor {MIN_RESOLVED}) — the resolver "
            "lost a dispatch convention"
        )

    def test_the_hand_fixed_tools_stay_inside_the_wider_guard(self) -> None:
        outside = sorted(ALIGNED_TOOL_NAMES - set(RESOLVED))
        assert not outside, f"{outside}: the 20-tool alignment fell out of the resolver"


class TestNoPhantomFieldsAcrossSurface:
    """No tool may declare a field its emitter cannot write."""

    @pytest.mark.parametrize("name", _CHECKABLE)
    def test_declared_fields_exist_in_emitter_source(self, name: str) -> None:
        emitted = _emitted(name)
        assert emitted, f"{name}: emitter modules not found: {RESOLVED[name]}"
        phantom = sorted(_declared(name) - emitted)
        assert not phantom, (
            f"{name}: outputSchema declares {phantom} but {list(RESOLVED[name])} never "
            "emits it — align the schema to the payload or drop the field"
        )

    def test_checkable_set_covers_most_of_the_surface(self) -> None:
        assert len(_CHECKABLE) >= MIN_RESOLVED - 10, (
            f"only {len(_CHECKABLE)} tools have a checkable data shape"
        )
