# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Map a PRY tool to the domain module its guarded dispatcher calls.

``pry_mcp/tools`` contains two dispatch styles, and each names its emitter in
code: an ``if name == "pry_x":`` branch imports the handler inline, while a
``*_TOOL_FNS`` registry holds a module *short* name (``odds``) next to the
package the dispatcher resolves it inside (``sports_data``). Reading both keeps
the schema guard current without a curated per-tool table.
"""

from __future__ import annotations

import ast
import functools
import pathlib

from ._emitter_scan import _parsed, module_files

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TOOLS_DIR = _REPO_ROOT / "pry_mcp" / "tools"


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _sources() -> list[tuple[pathlib.Path, ast.Module]]:
    return [(path, tree) for path in sorted(_TOOLS_DIR.glob("*.py")) if (tree := _parsed(path))]


def _dict_value(node: ast.AST) -> ast.Dict | None:
    """The dict literal assigned by a ``*_TOOL_FNS`` statement, if any."""
    target = node.target if isinstance(node, ast.AnnAssign) else None
    if isinstance(target, ast.Name) and target.id.endswith("TOOL_FNS"):
        return node.value if isinstance(node.value, ast.Dict) else None
    if isinstance(node, ast.Assign):
        first = node.targets[0]
        if isinstance(first, ast.Name) and first.id.endswith("TOOL_FNS"):
            return node.value if isinstance(node.value, ast.Dict) else None
    return None


@functools.cache
def dispatch_packages() -> tuple[str, ...]:
    """Every package a guarded dispatcher resolves domain modules inside."""
    packages: set[str] = set()
    for _, tree in _sources():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            index = {"resolve_domain_module": 0, "_call_domain_dispatcher": 2}.get(name)
            if index is None or len(node.args) <= index:
                continue
            arg = node.args[index]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                packages.add(arg.value)
    return tuple(sorted(packages))


@functools.cache
def registry_modules() -> dict[str, set[str]]:
    """Tool -> module short names declared by the ``*_TOOL_FNS`` registries."""
    found: dict[str, set[str]] = {}
    for _, tree in _sources():
        for node in ast.walk(tree):
            value = _dict_value(node)
            if value is None:
                continue
            for key, entry in zip(value.keys, value.values, strict=False):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if not isinstance(entry, ast.Tuple):
                    continue
                for option in entry.elts:
                    if not isinstance(option, ast.Tuple) or not option.elts:
                        continue
                    short = option.elts[0]
                    if isinstance(short, ast.Constant) and isinstance(short.value, str):
                        found.setdefault(key.value, set()).add(short.value)
    return found


@functools.cache
def inline_modules() -> dict[str, set[str]]:
    """Tool -> absolute modules imported inside its ``if name ==`` branch."""
    found: dict[str, set[str]] = {}
    for _, tree in _sources():
        for node in ast.walk(tree):
            if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
                continue
            left = node.test.left
            if not (isinstance(left, ast.Name) and left.id == "name"):
                continue
            tools = [
                term.value
                for term in node.test.comparators
                if isinstance(term, ast.Constant) and isinstance(term.value, str)
            ]
            modules = {
                sub.module
                for sub in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                if isinstance(sub, ast.ImportFrom) and sub.module and not sub.level
            }
            for tool in tools:
                if modules:
                    found.setdefault(tool, set()).update(modules)
    return found


def _expand(short: str) -> set[str]:
    """Dotted modules for a registry short name (``odds`` -> ``sports_data.odds``)."""
    if "." in short:
        return {short}
    expanded = {
        f"{package}.{short}"
        for package in dispatch_packages()
        if module_files(f"{package}.{short}")
    }
    return expanded or ({short} if module_files(short) else set())


@functools.cache
def tool_local_modules() -> dict[str, tuple[str, ...]]:
    """Tool -> modules its local (non-REST) dispatch path can call."""
    resolved: dict[str, set[str]] = {}
    for tool, shorts in registry_modules().items():
        for short in shorts:
            resolved.setdefault(tool, set()).update(_expand(short))
    for tool, modules in inline_modules().items():
        resolved.setdefault(tool, set()).update(modules)
    return {tool: tuple(sorted(modules)) for tool, modules in resolved.items() if modules}
