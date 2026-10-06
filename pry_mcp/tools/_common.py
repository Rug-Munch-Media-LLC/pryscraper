"""Pry - MCP tool definitions: shared dispatch helpers used by the per-domain dispatcher modules..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import importlib
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
    (or its containing package) does not exist. Anything else — a dependency the
    candidate itself imports — means the candidate exists and is broken.
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
                    {
                        "error": f"{tool_name} requires {arg}",
                        "code": "MISSING_ARGUMENT",
                    }
                ),
            }
        ],
        "isError": True,
    }


def _callable_accepts(fn: Any, kwarg: str) -> bool:
    """Best-effort: does the callable accept a keyword argument?"""
    import inspect

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError) as e:
        logger.warning(
            "suppressed %s in _callable_accepts (_common.py:158): %s",
            "(TypeError, ValueError)",
            e,
        )
        return True
    return kwarg in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _domain_module_unavailable(tool_name: str, package: str) -> dict[str, Any]:
    """MCP content dict for a climate/research tool whose module has not landed yet."""
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


def _domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for a climate/research tool from MCP arguments.

    Mirrors ``_sports_tool_kwargs``: kwargs the landed callable does not
    support are filtered out by the dispatcher (``_callable_accepts``) so the
    call never fails on an unknown keyword.
    """
    if name == "pry_weather":
        kwargs: dict[str, Any] = {"location": arguments.get("location", "")}
        if arguments.get("latitude") is not None and arguments.get("longitude") is not None:
            kwargs["location"] = f"{arguments['latitude']},{arguments['longitude']}"
        if arguments.get("forecast_days") is not None:
            kwargs["days"] = int(arguments["forecast_days"])
        return kwargs
    if name == "pry_agri":
        kwargs = {
            "commodity": arguments.get("crop", "") or arguments.get("commodity", ""),
            "state": arguments.get("region", "all") or arguments.get("state", "all"),
            "limit": int(arguments.get("limit", 20)),
        }
        return kwargs
    if name == "pry_papers":
        kwargs = {"query": arguments.get("query", ""), "limit": int(arguments.get("limit", 20))}
        if arguments.get("author"):
            kwargs["author"] = arguments["author"]
        if arguments.get("year_from") is not None:
            kwargs["year_from"] = int(arguments["year_from"])
        return kwargs
    if name == "pry_domain":
        kwargs = {"domain": arguments.get("domain", "")}
        if arguments.get("include_tech") is not None:
            kwargs["include_tech"] = bool(arguments["include_tech"])
        return kwargs
    return dict(arguments)


def _apply_offset(data: Any, arguments: dict[str, Any]) -> tuple[Any, int]:
    """Apply ``offset`` pagination to a list-shaped handler result.

    Returns ``(page, total)`` where ``total`` is the pre-slice length. When
    ``offset`` is absent/0 the data passes through unchanged. Non-list data
    (dicts, scalars) is returned untouched with total 0.
    """
    if not isinstance(data, list):
        return data, 0
    total = len(data)
    try:
        offset = int(arguments.get("offset") or 0)
    except (TypeError, ValueError) as e:
        logger.warning(
            "suppressed %s in _apply_offset (_common.py:232): %s",
            "(TypeError, ValueError)",
            e,
        )
        offset = 0
    if offset <= 0:
        return data, total
    return data[offset:], total


async def _call_domain_dispatcher(
    name: str,
    arguments: dict[str, Any],
    package: str,
    registry: dict[str, tuple[tuple[str, tuple[str, ...]], ...]],
    kwargs_builder: Any,
    required_args: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Run a climate/research tool via a candidate registry with guarded import.

    Tries each (module, candidates) option in order; the first landed module
    that exposes one of the candidate callables wins. Missing required
    arguments are reported as a tool error; a fully missing module degrades
    to a readable "not available" message.
    """
    entry = registry.get(name)
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
        try:
            _offset = int(arguments.get("offset") or 0)
        except (TypeError, ValueError) as e:
            logger.warning(
                "suppressed %s in _call_domain_dispatcher (_common.py:273): %s",
                "(TypeError, ValueError)",
                e,
            )
            _offset = 0
        if _offset > 0:
            kwargs["limit"] = int(kwargs.get("limit") or 20) + _offset
        result = fn(**{k: v for k, v in kwargs.items() if _callable_accepts(fn, k)})
        # Handlers are usually async (events/freight/energy/...) but some
        # landed modules expose sync registry reads (app-store/news/
        # compliance/deals) — await only when the callable returned a
        # coroutine.
        import inspect

        if inspect.isawaitable(result):
            data = await result
        else:
            data = result
        data, total = _apply_offset(data, arguments)
        payload: dict[str, Any] = {"success": True, "data": data}
        if total:
            payload["total"] = total
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, indent=2),
                }
            ],
            "isError": False,
        }
    return _domain_module_unavailable(name, package)


def _broad_domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for an events/freight/energy/food/supply tool.

    Mirrors ``_domain_tool_kwargs`` / ``_new_domain_tool_kwargs``: kwargs the
    landed callable does not support are filtered out by the dispatcher
    (``_callable_accepts``) so the call never fails on an unknown keyword.
    """
    if name == "pry_events":
        return {
            "query": arguments.get("query", ""),
            "limit": int(arguments.get("limit", 20)),
        }
    if name == "pry_resale":
        return {"event_id": arguments.get("event_id", "")}
    if name == "pry_freight":
        kwargs: dict[str, Any] = {"route": arguments.get("route", "")}
        if arguments.get("origin"):
            kwargs["origin"] = arguments["origin"]
        if arguments.get("destination"):
            kwargs["destination"] = arguments["destination"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_energy_lmp":
        kwargs = {"region": arguments.get("region", "") or arguments.get("region_id", "")}
        if arguments.get("date"):
            kwargs["date"] = arguments["date"]
        return kwargs
    if name == "pry_grocery":
        # The landed handler is ``get_grocery_prices(query, zip_code, limit)``;
        # it treats zip as required, so the MCP ``zip`` argument maps to
        # ``zip_code`` rather than being dropped by ``_callable_accepts``.
        kwargs = {
            "query": arguments.get("query", "") or arguments.get("item", ""),
            "zip_code": arguments.get("zip", "") or arguments.get("zip_code", ""),
        }
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_restaurant":
        kwargs = {"name": arguments.get("name", "")}
        if arguments.get("location"):
            kwargs["location"] = arguments["location"]
        return kwargs
    if name == "pry_imports":
        kwargs = {"company": arguments.get("company", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_firmographics":
        return {"company": arguments.get("company", "")}
    return dict(arguments)


def _new_domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for an app-store / news / compliance / deals tool.

    Mirrors ``_broad_domain_tool_kwargs`` / ``_domain_tool_kwargs``: kwargs
    the landed callable does not support are filtered out by the dispatcher
    (``_callable_accepts``) so the call never fails on an unknown keyword.
    """
    if name == "pry_app_search":
        kwargs: dict[str, Any] = {"query": arguments.get("query", "")}
        if arguments.get("country"):
            kwargs["country"] = arguments["country"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_app_reviews":
        kwargs = {"app_id": arguments.get("app_id", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_news":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("language"):
            kwargs["language"] = arguments["language"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_sentiment":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_compliance":
        kwargs = {}
        if arguments.get("query"):
            kwargs["query"] = arguments["query"]
        if arguments.get("agency"):
            kwargs["agency"] = arguments["agency"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_company_watch":
        kwargs = {"company": arguments.get("company", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_deals":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_drop_alert":
        kwargs = {"product": arguments.get("product", "")}
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_contracts":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("agency"):
            kwargs["agency"] = arguments["agency"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    if name == "pry_grants":
        kwargs = {"query": arguments.get("query", "")}
        if arguments.get("agency"):
            kwargs["agency"] = arguments["agency"]
        if arguments.get("limit") is not None:
            kwargs["limit"] = int(arguments["limit"])
        return kwargs
    return dict(arguments)
