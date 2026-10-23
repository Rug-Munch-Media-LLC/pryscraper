"""Pry - MCP tool definitions: kwargs builders for appstore / news / compliance / deals / bidding domains.

Extracted from ``_common.py`` to keep the core utilities focused.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _new_domain_tool_kwargs(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Build the kwargs for an app-store / news / compliance / deals tool from MCP arguments.

    Mirrors ``_broad_domain_tool_kwargs`` / ``_domain_tool_kwargs``: kwargs the
    landed callable does not support are filtered out by the dispatcher
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
