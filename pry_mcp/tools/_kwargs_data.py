"""Data-domain kwargs builder, extracted to avoid a data <-> data_* cycle."""

from __future__ import annotations

from typing import Any


def _broad_domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for an events / freight / energy / food / supply tool.

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

