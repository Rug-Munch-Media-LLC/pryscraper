"""Company-registry search/detail via state Secretary of State public APIs.

Primary source: **Nevada Secretary of State** business entity search JSON API
(https://nv-sos.elb.us-eas-2.aws.sos.nv.gov/api/CorpSearch/Search) — the
public, keyless JSON endpoint that powers the state's Business Entity
Search page. No API key, no registration.

The state is configurable: ``PRY_COMPANY_STATE`` selects the default state
code (``NV``) and :data:`STATE_REGISTRIES` maps state codes to their
search configuration. Adding a new state is a table row + a row normalizer,
so the module stays a single documented example with a clean extension
point rather than a per-state scraping zoo.

The public entrypoints are async functions that never raise:

* :func:`search_companies` — query a state registry; returns a normalized
  list:

      {
          "name": str,
          "entity_id": str,          # state business id, "" when unknown
          "type": str,               # entity type, e.g. "Domestic Corporation"
          "status": str,             # e.g. "Active" | "Default"
          "state": str,              # state code, e.g. "NV"
          "formation_date": str,     # ISO-8601, "" when unknown
          "registered_agent": str,   # "" when unlisted
      }

* :func:`get_company` — best-match company detail for a name/state; same
  shape as one search item, ``{}`` when no match is found.

On any failure (HTTP error, timeout, malformed JSON, unsupported state,
empty results) the functions degrade to ``[]`` / ``{}`` and log — they
never raise.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from client import get_client

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
MAX_LIMIT = 100

DEFAULT_STATE = os.getenv("PRY_COMPANY_STATE", "NV").strip().upper() or "NV"

# ── State registry configuration ─────────────────────────────────────────
# Each entry describes how to query that state's Secretary of State search
# JSON API: url template, query params, JSON path to the row list, and the
# field-name candidates used by the normalizer. Nevada is the canonical
# documented example (its own search page consumes this endpoint).
STATE_REGISTRIES: dict[str, dict[str, Any]] = {
    "NV": {
        "name": "Nevada Secretary of State",
        "search_url": "https://nv-sos.elb.us-eas-2.aws.sos.nv.gov/api/CorpSearch/Search",
        "params": {"searchType": "All", "pageNumber": "1"},
        "rows_path": ("rows",),
        "fields": {
            "name": ("businessName", "entityName", "name"),
            "entity_id": ("businessId", "entityId", "id"),
            "type": ("entityType", "type"),
            "status": ("status",),
            "formation_date": ("formationDate", "filingDate", "dateFormed"),
            "registered_agent": ("registeredAgentName", "agentName", "registeredAgent"),
        },
    },
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _first(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value) not in ("", "None", "null"):
            return _text(value)
    return ""


def _dig(container: Any, path: tuple[str, ...]) -> Any:
    """Walk a nested dict/list by a tuple of keys (returns None on miss)."""
    node = container
    for key in path:
        if isinstance(node, dict):
            node = node.get(key)
        elif isinstance(node, list) and isinstance(key, int) and key < len(node):
            node = node[key]
        else:
            return None
    return node


def _normalize_row(row: dict[str, Any], state: str) -> dict[str, Any]:
    config = STATE_REGISTRIES.get(state, {})
    fields = config.get("fields", {})
    return {
        "name": _first(row, *fields.get("name", ("name",))),
        "entity_id": _first(row, *fields.get("entity_id", ("entity_id",))),
        "type": _first(row, *fields.get("type", ("type",))),
        "status": _first(row, *fields.get("status", ("status",))),
        "state": state,
        "formation_date": _first(row, *fields.get("formation_date", ("formation_date",))),
        "registered_agent": _first(row, *fields.get("registered_agent", ("registered_agent",))),
    }


def _is_supported(state: str) -> bool:
    return state in STATE_REGISTRIES


def _clamp_limit(limit: int) -> int:
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        return 20


async def search_companies(name: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search a state company registry by business name.

    Args:
        name: Business name to search for (case-insensitive on the API).
        limit: Max results to return (clamped to 1-100).

    Returns:
        Normalized company records; ``[]`` on any failure (never raises).
    """
    name = str(name or "").strip()
    if not name:
        return []
    limit = _clamp_limit(limit)
    state = DEFAULT_STATE
    if not _is_supported(state):
        logger.warning(
            "company_registry_unsupported_state",
            extra={"state": state, "supported": sorted(STATE_REGISTRIES)},
        )
        return []
    config = STATE_REGISTRIES[state]
    params: dict[str, Any] = {
        "searchValue": name,
        "pageSize": limit,
        **config.get("params", {}),
    }
    try:
        client = await get_client()
        response = await client.get(
            config["search_url"],
            params=params,
            timeout=HTTP_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        rows = _dig(payload, config.get("rows_path", ("rows",))) or []
        items = [_normalize_row(row, state) for row in rows if isinstance(row, dict)]
        items = [item for item in items if item["name"]]
        logger.info(
            "company_registry_search",
            extra={"state": state, "query": name, "results": len(items), "limit": limit},
        )
        return items[:limit]
    except (httpx.HTTPError, ValueError, TypeError, OSError) as exc:
        logger.warning(
            "company_registry_search_failed",
            extra={"state": state, "query": name, "error": str(exc)},
        )
        return []


async def get_company(name: str, state: str | None = None) -> dict[str, Any]:
    """Fetch a single company by name, preferring an exact-name match.

    Args:
        name: Business name to look up.
        state: Two-letter state code; defaults to ``PRY_COMPANY_STATE`` / NV.

    Returns:
        Best-match normalized company record, ``{}`` when no match is found
        or the state is unsupported. Never raises.
    """
    name = str(name or "").strip()
    if not name:
        return {}
    state = str(state or DEFAULT_STATE).strip().upper()
    if not _is_supported(state):
        logger.warning(
            "company_registry_unsupported_state",
            extra={"state": state, "supported": sorted(STATE_REGISTRIES)},
        )
        return {}
    results = await search_companies(name, limit=20)
    if not results:
        return {}
    wanted = name.lower()
    for record in results:
        if record["name"].lower() == wanted:
            return record
    # No exact match — the top-ranked fuzzy result is the best available.
    return results[0]
