"""GraphQL tier — endpoint discovery (Apollo/Hasura markers) and guarded queries."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

from pry.engine.methods import _common
from pry.engine.methods._common import _origin_of, _resolve_candidate

_GRAPHQL_QUOTED_RE = re.compile(
    r"""["']([^"']*(?:graphql|apollo|hasura|gql)[^"']*)["']""", re.IGNORECASE
)
_GRAPHQL_URI_ATTR_RE = re.compile(
    r"""(?:uri|endpoint|url)\s*[:=]\s*["']([^"']*)["']""", re.IGNORECASE
)
_GRAPHQL_SCRIPT_SRC_RE = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.IGNORECASE)
_GRAPHQL_BUNDLE_MARKERS = ("graphql", "gql", "apollo", "hasura")
_HASURA_ATTR_RE = re.compile(r"data-hasura-[a-z0-9-]+", re.IGNORECASE)
_APOLLO_STATE_MARKER = "__APOLLO_STATE__"


def discover_graphql(page_url: str, html: str) -> list[str]:
    """Discover GraphQL endpoint candidates from a page's HTML.

    Scans (a) quoted references containing ``graphql`` / ``apollo`` /
    ``hasura`` / ``gql`` (e.g. ``"/graphql"``), (b) Apollo-style
    ``uri:`` / ``endpoint:`` / ``url:`` configuration, (c) ``<script src>``
    bundle URLs that look GraphQL-related, and (d) convention markers: a
    ``data-hasura-*`` attribute implies the standard ``/v1/graphql`` endpoint
    on the page origin and an ``__APOLLO_STATE__`` marker implies the standard
    ``/graphql`` endpoint. All relative references resolve against
    ``page_url``.

    Args:
        page_url: The URL the HTML was fetched from.
        html: Raw page HTML.

    Returns:
        De-duplicated, absolute candidate URLs (ordered by discovery).
        Never raises: returns ``[]`` for unusable input.
    """
    if not isinstance(page_url, str) or not isinstance(html, str):
        return []
    page_url = page_url.strip()
    if not page_url or not html:
        return []

    candidates: list[str] = []
    for match in _GRAPHQL_QUOTED_RE.finditer(html):
        if match.lastindex is None:
            continue
        value = match.group(1).strip()
        if value:
            candidates.append(value)
    for match in _GRAPHQL_URI_ATTR_RE.finditer(html):
        if match.lastindex is None:
            continue
        value = match.group(1).strip()
        if value and any(marker in value.lower() for marker in _GRAPHQL_BUNDLE_MARKERS):
            candidates.append(value)
    for src in _GRAPHQL_SCRIPT_SRC_RE.findall(html):
        lowered = src.lower()
        if any(marker in lowered for marker in _GRAPHQL_BUNDLE_MARKERS):
            candidates.append(src)
    origin = _origin_of(page_url)
    if origin is not None:
        if _HASURA_ATTR_RE.search(html):
            candidates.append(urljoin(origin, "/v1/graphql"))
        if _APOLLO_STATE_MARKER in html:
            candidates.append(urljoin(origin, "/graphql"))

    seen: set[str] = set()
    urls: list[str] = []
    for raw in candidates:
        resolved = _resolve_candidate(raw, page_url)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        urls.append(resolved)
    return urls


def query_graphql(
    endpoint: str,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """POST a GraphQL query to an endpoint and return the JSON payload.

    Sends ``{"query": query, "variables": variables or {}}`` as JSON. The
    endpoint is SSRF-validated before the request.

    Args:
        endpoint: Absolute http(s) GraphQL endpoint URL.
        query: GraphQL query document.
        variables: Optional variables dict (defaults to ``{}``).

    Returns:
        The parsed JSON payload when the response is valid JSON, else None.
        Never raises.
    """
    if not isinstance(endpoint, str) or not isinstance(query, str):
        return None
    if not endpoint.strip() or not query.strip():
        return None
    response = _common._sync_post(
        endpoint, json_body={"query": query, "variables": variables or {}}
    )
    if response is None:
        return None
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = ["discover_graphql", "query_graphql"]
