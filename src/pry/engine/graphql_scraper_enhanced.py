# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
"""Pry — GraphQL API Scraper (Tier 15).

Discovers and scrapes GraphQL endpoints. Many modern websites expose
GraphQL APIs that are easier to query than scraping HTML.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Common GraphQL endpoint patterns
GRAPHQL_ENDPOINTS = [
    "/graphql",
    "/api/graphql",
    "/graphql/v1",
    "/api/v1/graphql",
    "/gql",
    "/api/gql",
    "/graphql/api",
    "/_graphql",
]


class GraphQLScraper:
    """Discover and scrape GraphQL APIs."""

    def __init__(self):
        self._endpoint_index = 0

    def is_available(self) -> bool:
        return True

    async def scrape(self, url: str, opts: dict[str, Any] | None = None) -> str | None:
        """Scrape via GraphQL introspection and queries."""
        try:
            import httpx

            opts = opts or {}
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            async with httpx.AsyncClient(timeout=30) as client:
                for endpoint in GRAPHQL_ENDPOINTS:
                    try:
                        # Try introspection query
                        resp = await client.post(
                            f"{base_url}{endpoint}",
                            json={"query": INTROSPECTION_QUERY},
                            headers={
                                "Content-Type": "application/json",
                                "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)",
                            },
                        )
                        if resp.is_success and "data" in resp.text:
                            data = resp.json()
                            if data.get("data", {}).get("__schema"):
                                return json.dumps(data, indent=2)
                    except Exception as e:
                        logger.debug(
                            "graphql_endpoint_probe_failed",
                            extra={"endpoint": endpoint, "error": str(e)[:80]},
                        )
                        continue

            return None
        except Exception as e:
            logger.debug("graphql_scraper_failed", extra={"error": str(e)[:50]})
            return None


INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      ...FullType
    }
  }
}
fragment FullType on __Type {
  kind
  name
  description
  fields(includeDeprecated: true) {
    name
    description
    type {
      ...TypeRef
    }
  }
  inputFields {
    name
    type {
      ...TypeRef
    }
  }
  interfaces {
    ...TypeRef
  }
  enumValues(includeDeprecated: true) {
    name
  }
  possibleTypes {
    ...TypeRef
  }
}
fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
    }
  }
}
"""
