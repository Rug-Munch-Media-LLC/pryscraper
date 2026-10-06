"""Pry — GraphQL Auto-Discovery.
Detects GraphQL endpoints, runs introspection queries, generates optimized queries.
Many modern sites (Shopify, GitHub, Twitter/X, etc.) have GraphQL APIs that are
10-100x more efficient than scraping HTML."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import logging
import re
from typing import Any, ClassVar

import httpx

from pry.engine.url_guard import validate_url

logger = logging.getLogger(__name__)


class GraphQLDiscovery:
    """Auto-discover and query GraphQL endpoints."""

    # Common paths where GraphQL endpoints live
    COMMON_PATHS: ClassVar[list[str]] = [
        "/graphql",
        "/api/graphql",
        "/api/v1/graphql",
        "/v1/graphql",
        "/v2/graphql",
        "/graphql/v1",
        "/graphql/v2",
        "/gql",
        "/api/gql",
        "/query",
        "/api/query",
        "/__graphql",
        "/altair",
        "/playground",
    ]

    # Patterns in JS bundles that indicate GraphQL endpoints
    ENDPOINT_PATTERNS: ClassVar[list[str]] = [
        r'["\']([/][\w/]*graphql[\w/]*)["\']',
        r'["\'](https?://[^/"\']*[/][\w/]*graphql[\w/]*)["\']',
        r'apolloClient\s*\.\s*link\s*\(\s*["\']([^"\']+)["\']',
        r'createHttpLink\s*\(\s*{\s*uri:\s*["\']([^"\']+)["\']',
        r'endpoint["\']:\s*["\']([^"\']+graphql[^"\']*)["\']',
        r'uri["\']:\s*["\']([^"\']*graphql[^"\']*)["\']',
    ]

    INTROSPECTION_QUERY = """
    # Standard graphql introspection query
    query IntrospectionQuery {
        __schema {
            queryType { name }
            mutationType { name }
            subscriptionType { name }
            types {
                kind name
                fields { name type { name kind ofType { name kind ofType { name } } } }
            }
        }
    }
    """

    def __init__(self) -> None:
        self.discovered: dict[str, dict[str, Any]] = {}

    async def discover(self, base_url: str) -> list[dict[str, Any]]:
        """Discover GraphQL endpoints for a given base URL."""
        from pry.api.client import get_client

        client = await get_client()
        found: list[dict[str, Any]] = []
        for path in self.COMMON_PATHS:
            url = base_url.rstrip("/") + path
            try:
                # SSRF gate: each candidate endpoint is a user-derived URL.
                validate_url(url)
                resp = await client.post(url, json={"query": "{ __typename }"}, timeout=10)
                if resp.is_success:
                    try:
                        data = resp.json()
                    except (json.JSONDecodeError, ValueError):
                        logger.warning("silent_exception_swallowed", exc_info=True)
                        continue
                    if "data" in data or "errors" in data:
                        found.append({"url": url, "method": "path_probe"})
                        self.discovered[url] = data
            except (httpx.HTTPError, httpx.RequestError) as e:
                logger.debug("graphql_probe_failed", extra={"url": url, "err": str(e)[:100]})
        return found

    async def introspect(self, endpoint: str) -> dict[str, Any]:
        """Run GraphQL introspection to get the full schema."""
        from pry.api.client import get_client

        client = await get_client()
        try:
            # SSRF gate: endpoint is user-supplied.
            validate_url(endpoint)
            resp = await client.post(endpoint, json={"query": self.INTROSPECTION_QUERY}, timeout=30)
            if resp.is_success:
                return resp.json()
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("silent_exception_swallowed", exc_info=True)
            return {"error": str(e)[:300]}
        return {}

    async def query(
        self, endpoint: str, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL query."""
        from pry.api.client import get_client

        client = await get_client()
        try:
            # SSRF gate: endpoint is user-supplied.
            validate_url(endpoint)
            resp = await client.post(
                endpoint,
                json={"query": query, "variables": variables or {}},
                timeout=30,
            )
            if resp.is_success:
                return resp.json()
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("silent_exception_swallowed", exc_info=True)
            return {"error": str(e)[:300]}
        return {}

    def extract_endpoints_from_js(self, js_content: str) -> list[str]:
        """Scan a JS bundle for embedded GraphQL endpoint strings.

        Returns a de-duplicated list of potential endpoint URLs/paths.
        """
        candidates: list[str] = []
        for pattern in self.ENDPOINT_PATTERNS:
            for match in re.finditer(pattern, js_content):
                if match.lastindex is None:
                    continue
                value = match.group(1).strip()
                if value:
                    candidates.append(value)
        # De-duplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique
