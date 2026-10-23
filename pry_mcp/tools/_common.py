"""Pry - MCP tool definitions: shared dispatch helpers used by the per-domain dispatcher modules.

Split from the former monolithic ``pry_mcp/tools.py`` god file.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import importlib
import inspect
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

logger = logging.getLogger(__name__)

# Every data domain (``food_data``, ``sports_data``, ``gov_data``, ...) is a
# subpackage of the top-level ``datasets`` package — the same namespace the REST
# routers import through (``src/pry/api/routers/data/*.py``:
# ``importlib.import_module(f"datasets.{package}.{module_name}")``). There is
# no bare top-level ``food_data`` / ``sports_data`` / ``gov_data`` directory,
# so a bare ``{package}.{module}`` import can never succeed.
DATASETS_PACKAGE = "datasets"


class _ModuleNotFound(Exception):
    """No candidate namespace held ``{package}.{module_name}``."""


def resolve_domain_module(package: str, module_name: str) -> ModuleType:
    """Import ``{package}.{module_name}`` from the namespace that holds it.

    Resolution is deterministic, not a best-effort chain. The domain packages
    live under ``datasets`` (``DATASETS_PACKAGE``) — the namespace the REST
    routers import them from — so ``datasets.{package}.{module_name}`` is the
    canonical path and is tried first. A top-level ``{package}.{module}`` is
    attempted only as a compatibility fallback, so the loader still works for a
    deployment that installs a domain package at the top level.

    A bare ``ModuleNotFoundError`` is not proof the module is absent: a module
    that exists but whose own import fails raises the same exception with
    ``exc.name`` naming the *missing dependency*, not the module we asked for.
    Swallowing that would report a broken module as "not landed yet", so it is
    distinguished by ``exc.name`` and re-raised. The namespace genuinely does
    not hold the module when the missing name is the candidate itself or one of
    its parents (a parent package that is absent).

    Raises ``_ModuleNotFound`` when no namespace holds the module. Callers turn
    that into the ``MODULE_UNAVAILABLE`` payload, so a module that does exist is
    never reported unavailable and one that genuinely has not landed still
    degrades to a readable message.
    """
    dotted = f"{package}.{module_name}"
    for candidate in (f"{DATASETS_PACKAGE}.{dotted}", dotted):
        try:
            return importlib.import_module(candidate)
        except ModuleNotFoundError as exc:
            if not _absent_from_namespace(candidate, exc.name):
                logger.debug(
                    "domain module present but its own import failed",
                    extra={"candidate": candidate, "missing_name": exc.name},
                )
                raise
            logger.debug(
                "domain module namespace miss",
                extra={"candidate": candidate},
            )
    raise _ModuleNotFound(dotted)


def resolve_domain_package(package: str) -> ModuleType:
    """Import the ``datasets.{package}`` subpackage itself.

    Some registries name a package rather than a module (``gov_data`` re-exports
    ``search_opportunities`` / ``search_recalls`` from its ``__init__``). Same
    namespace rule and the same missing-name distinction as
    ``resolve_domain_module``.
    """
    candidates = (f"{DATASETS_PACKAGE}.{package}", package)
    for candidate in candidates:
        try:
            return importlib.import_module(candidate)
        except ModuleNotFoundError as exc:
            if not _absent_from_namespace(candidate, exc.name):
                logger.debug(
                    "domain package present but its own import failed",
                    extra={"candidate": candidate, "missing_name": exc.name},
                )
                raise
            logger.debug("domain package namespace miss", extra={"candidate": candidate})
    raise _ModuleNotFound(package)


def _absent_from_namespace(candidate: str, missing_name: str | None) -> bool:
    """Does ``missing_name`` mean ``candidate`` is absent, rather than broken?

    ``missing_name`` names the module or one of its parents when the candidate
    namespace is genuinely absent; it names a dependency when the candidate
    exists but is broken.
    """
    if not missing_name:
        return False
    return candidate == missing_name or candidate.startswith(f"{missing_name}.")


def _data_module_unavailable(tool_name: str, package: str) -> dict[str, Any]:
    """MCP content dict for a data-domain tool whose module has not landed yet."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": (
                            f"Tool {tool_name} is not available yet: the {package} module has "
                            "not finished landing (parallel build in progress). Try again shortly."
                        ),
                        "code": "MODULE_UNAVAILABLE",
                    }
                ),
            }
        ],
        "isError": False,
    }


def _missing_arg(tool_name: str, arg: str) -> dict[str, Any]:
    """MCP content dict for a missing required argument (structured error)."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"error": f"{tool_name} requires {arg}", "code": "MISSING_ARGUMENT"}
                ),
            }
        ],
        "isError": True,
    }


def _callable_accepts(fn: Any, kwarg: str) -> bool:
    """Return ``True`` if ``fn`` accepts ``kwarg`` (including ``**kwargs``)."""
    try:
        params = inspect.signature(fn).parameters
        return kwarg in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
    except Exception as e:  # noqa: BLE001 — suppress signature inspection failures
        logger.warning(
            "suppressed %s in _callable_accepts (_common.py:158): %s",
            type(e).__name__,
            e,
        )
        return False


def _apply_offset(data: Any, arguments: dict[str, Any]) -> tuple[Any, int]:
    """Apply ``offset`` pagination to a list-shaped handler result.

    Returns ``(page, total)`` where ``total`` is the pre-slice length.
    When ``offset`` is absent/0 the data passes through unchanged.
    """
    try:
        offset = int(arguments.get("offset") or 0)
    except Exception as e:  # noqa: BLE001 — suppress bad offset values
        logger.warning(
            "suppressed %s in _apply_offset (_common.py:232): %s",
            type(e).__name__,
            e,
        )
        return data, 0
    if offset <= 0:
        return data, 0
    if not isinstance(data, list):
        return data, 0
    total = len(data)
    page = data[offset : offset + int(arguments.get("limit") or 20)]
    return page, total


async def _call_domain_dispatcher(
    name: str,
    arguments: dict[str, Any],
    package: str,
    tool_fns: dict[str, tuple[tuple[str, tuple[str, ...]], ...]],
    kwargs_builder: Any,
    required_args: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Call one guarded domain dispatcher; ``None`` means "not mine" (lazy import).

    ``tool_fns`` maps tool name to a tuple of (module_name, candidate_callables).
    ``kwargs_builder`` is a ``(name, arguments) -> dict`` callable that builds the
    kwargs for the specific domain. ``required_args`` optionally enforces that
    certain tools have specific required arguments.
    """

    entry = tool_fns.get(name)
    if entry is None:
        return None

    required_args = required_args or {"pry_papers": "query", "pry_domain": "domain"}

    if name in required_args and not arguments.get(required_args[name]):
        return _missing_arg(name, required_args[name])

    for module_name, candidates in entry:
        try:
            mod = resolve_domain_module(package, module_name)
        except _ModuleNotFound as e:
            logger.warning(
                "suppressed %s in _call_domain_dispatcher (_common.py:263): %s",
                "_ModuleNotFound",
                e,
            )
            continue
        fn = next((getattr(mod, cand, None) for cand in candidates if hasattr(mod, cand)), None)
        if fn is None:
            continue
        kwargs = kwargs_builder(name, arguments)

        # Offset pagination: over-fetch by ``offset`` so the slice below
        # still yields a full ``limit``-sized page past the skipped rows.
        _offset = int(arguments.get("offset") or 0)
        if _offset > 0:
            kwargs["limit"] = int(kwargs.get("limit") or 20) + _offset

        try:
            result = fn(**{k: v for k, v in kwargs.items() if _callable_accepts(fn, k)})
        except Exception as e:  # noqa: BLE001 — surface handler failures as MCP errors
            logger.warning(
                "suppressed %s in _call_domain_dispatcher (_common.py:273): %s",
                type(e).__name__,
                e,
            )
            continue
        if inspect.isawaitable(result):
            data = await result
        else:
            data = result
        page, _ = _apply_offset(data, arguments)
        return {
            "content": [
                {"type": "text", "text": json.dumps({"success": True, "data": page}, indent=2)}
            ],
            "isError": False,
        }

    # If we exhausted all candidates, the module genuinely hasn't landed yet.
    # Use a domain-specific unavailable message if available, else generic.
    if package == "climate_data" or package == "research_data":
        from ._kwargs_climate_research import _domain_module_unavailable as _dm_unavail
    else:
        _dm_unavail = _data_module_unavailable
    return _dm_unavail(name, package)

