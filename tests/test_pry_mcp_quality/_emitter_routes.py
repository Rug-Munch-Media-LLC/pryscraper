# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Resolve a REST-fallback tool to the module that actually emits its payload.

``pry_mcp.tool_routes.TOOL_ROUTES`` names a route per tool, but the route
handler is usually a thin proxy: it resolves the real emitter at call time with
``importlib.import_module(f"datasets.attention.{module_name}")`` and the name
comes from a literal a few lines up. Stopping at the router module reports every
domain field as a phantom, so this module follows the lazy hop: route -> handler
-> the literal handed to the lazy loader -> ``datasets.attention.serp``.

When the name is not a literal the whole named package is returned instead. The
guard stays coarse there on purpose — a missed emitter weakens the check, while
a guessed one fabricates phantoms that cost more than they catch.
"""

from __future__ import annotations

import ast
import functools
import pathlib

from ._emitter_scan import _parsed, module_dotted, module_files, package_modules

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_API_ROOT = _REPO_ROOT / "src" / "pry" / "api"
_HTTP_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
_LAZY_LOADER = "import_module"


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _literal_prefix(node: ast.Call) -> str | None:
    """The literal prefix of ``import_module(...)``'s argument (empty: unknown)."""
    if not node.args:
        return None
    argument = node.args[0]
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    if isinstance(argument, ast.JoinedStr):
        return "".join(part.value for part in argument.values if isinstance(part, ast.Constant))
    return None


def _lazy_loaders(tree: ast.Module) -> dict[str, str]:
    """Function name -> package prefix, for helpers that lazily load a module."""
    loaders: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and _call_name(call) == _LAZY_LOADER:
                prefix = _literal_prefix(call)
                if prefix:
                    loaders[node.name] = prefix
    return loaders


def _handlers(tree: ast.Module) -> dict[str, ast.AST]:
    """Normalized route path -> handler node."""
    found: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or _call_name(decorator) not in _HTTP_VERBS:
                continue
            if not decorator.args:
                continue
            route = decorator.args[0]
            if isinstance(route, ast.Constant) and isinstance(route.value, str):
                found.setdefault(route.value.rstrip("/") or "/", node)
    return found


@functools.cache
def _route_index() -> dict[str, tuple[str, ast.AST]]:
    """Normalized route path -> (owning module, handler node)."""
    index: dict[str, tuple[str, ast.AST]] = {}
    if not _API_ROOT.is_dir():
        return index
    for path in sorted(_API_ROOT.rglob("*.py")):
        tree = _parsed(path)
        if tree is None:
            continue
        dotted = module_dotted(path)
        for route, handler in _handlers(tree).items():
            index.setdefault(route, (dotted, handler))
    return index


def _emitters(dotted: str, tree: ast.Module, handler: ast.AST) -> set[str]:
    """Modules the handler's lazy loader can reach, resolved through its literal."""
    for name, prefix in _lazy_loaders(tree).items():
        literal: str | None = None
        for call in ast.walk(handler):
            if not isinstance(call, ast.Call) or _call_name(call) != name:
                continue
            for argument in call.args[:1]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    literal = argument.value
            if literal is not None:
                break
        if literal is not None and module_files(f"{prefix}{literal}"):
            return {f"{prefix}{literal}"}
        package = prefix.rstrip(".")
        modules = package_modules(package)
        if modules:
            return set(modules)
    return {dotted}


@functools.cache
def _tool_routes() -> dict[str, str]:
    """Tool -> REST path, read from ``pry_mcp.tool_routes.TOOL_ROUTES``."""
    tree = _parsed(_REPO_ROOT / "pry_mcp" / "tool_routes.py")
    if tree is None:
        return {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "TOOL_ROUTES" or not isinstance(node.value, ast.Dict):
            continue
        routes: dict[str, str] = {}
        for key, value in zip(node.value.keys, node.value.values, strict=False):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if not isinstance(value, ast.Tuple) or len(value.elts) < 2:
                continue
            path = value.elts[1]
            if isinstance(path, ast.Constant) and isinstance(path.value, str):
                routes[key.value] = path.value
        return routes
    return {}


def _lookup(route: str) -> tuple[str, ast.AST] | None:
    wanted = route.rstrip("/") or "/"
    index = _route_index()
    if wanted in index:
        return index[wanted]
    for path in sorted(index, key=len, reverse=True):
        if wanted.endswith(path) or path.endswith(wanted):
            return index[path]
    return None


@functools.cache
def tool_route_modules() -> dict[str, tuple[str, ...]]:
    """Tool -> modules its REST fallback can emit from."""
    resolved: dict[str, tuple[str, ...]] = {}
    for tool, route in _tool_routes().items():
        hit = _lookup(route)
        if hit is None:
            continue
        dotted, handler = hit
        tree = _parsed(_path_for(dotted))
        if tree is None:
            resolved[tool] = (dotted,)
            continue
        resolved[tool] = tuple(sorted(_emitters(dotted, tree, handler)))
    return resolved


def _path_for(dotted: str) -> pathlib.Path:
    candidates = module_files(dotted)
    return candidates[0] if candidates else _REPO_ROOT / "missing.py"
