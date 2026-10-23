# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Collect the string literals an emitter module tree can put on the wire.

A tool's ``outputSchema`` may only name fields its emitter can actually
produce. Reading the emitter source is the cheapest way to prove that without
fabricating a payload: every field name a normalizer writes is a string
literal somewhere in the module it lives in (or in the sibling module a thin
facade re-exports from), so a declared key that appears nowhere in that
closure is a phantom field — the defect class the 2026-10-23 alignment commits
removed.
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SEARCH_ROOTS = (_REPO_ROOT / "src", _REPO_ROOT / "datasets", _REPO_ROOT)
#: Facades re-export one hop (``datasets.crypto_market.token_launches`` ->
#: ``crypto_market.token_launches`` -> its sibling normalizers). Two hops
#: covers every emitter chain in the tree without walking the whole repo.
_MAX_HOPS = 2


def _module_files(dotted: str) -> list[pathlib.Path]:
    """Every file that can hold ``dotted`` across the layout roots.

    The same dotted name exists in two namespaces for a few domains: a
    ``datasets`` facade and the canonical top-level package it re-exports
    (``crypto_market.token_launches``). Returning every candidate keeps the
    literal scan from stopping at the facade and reporting its real emitter
    fields as phantoms.
    """
    relative = dotted.replace(".", "/")
    found = []
    for root in _SEARCH_ROOTS:
        for candidate in (root / f"{relative}.py", root / relative / "__init__.py"):
            if candidate.exists() and candidate not in found:
                found.append(candidate)
    return found


def _parsed(path: pathlib.Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _imported_modules(path: pathlib.Path) -> list[str]:
    """Absolute module names imported by ``path`` (relative imports skipped)."""
    tree = _parsed(path)
    if tree is None:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


def emitted_literals(dotted: str) -> set[str]:
    """Every string literal reachable from ``dotted`` within ``_MAX_HOPS``."""
    seen: set[pathlib.Path] = set()
    frontier = _module_files(dotted)
    literals: set[str] = set()
    for _ in range(_MAX_HOPS + 1):
        following: list[pathlib.Path] = []
        for path in frontier:
            if path in seen:
                continue
            seen.add(path)
            tree = _parsed(path)
            if tree is None:
                continue
            literals |= {
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            for name in _imported_modules(path):
                following.extend(_module_files(name))
        frontier = following
    return literals
