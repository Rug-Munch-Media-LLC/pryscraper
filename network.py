"""Pry — network capture and lazy load handling.
Captures XHR/fetch requests from JS-heavy SPAs and handles lazy content."""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def extract_api_calls_from_html(html: str) -> list[dict[str, Any]]:
    """Extract API call patterns from HTML/JS.

    Finds fetch(), XMLHttpRequest, axios, $.ajax patterns in inline scripts.
    """
    api_calls = []

    # Pattern 1: fetch() calls
    fetch_patterns = re.finditer(
        r'fetch\s*\(\s*["\']([^"\']+)["\']',
        html,
    )
    for m in fetch_patterns:
        api_calls.append({"method": "fetch", "url": m.group(1)})

    # Pattern 2: XMLHttpRequest
    xhr_patterns = re.finditer(
        r'XMLHttpRequest\.open\s*\(\s*["\'](GET|POST|PUT|DELETE)["\']\s*,\s*["\']([^"\']+)["\']',
        html,
    )
    for m in xhr_patterns:
        api_calls.append({"method": m.group(1), "url": m.group(2)})

    # Pattern 3: axios calls (axios.get(), axios.post(), axios('url'))
    axios_patterns = re.finditer(
        r'axios(?:\.\w+)?\s*\(\s*["\']([^"\']+)["\']',
        html,
    )
    for m in axios_patterns:
        api_calls.append({"method": "axios", "url": m.group(1)})

    # Pattern 4: $.ajax / $.get / $.post
    jquery_patterns = re.finditer(
        r'\$\.(?:ajax|get|post)\s*\(\s*["\']([^"\']+)["\']',
        html,
    )
    for m in jquery_patterns:
        api_calls.append({"method": "jquery", "url": m.group(1)})

    # Pattern 5: JSON API endpoints in script data-* attrs or config objects
    api_url_patterns = re.finditer(
        r'(?:apiUrl|api_url|endpoint|apiEndpoint|baseUrl)\s*[:=]\s*["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    for m in api_url_patterns:
        api_calls.append({"method": "config", "url": m.group(1)})

    # De-duplicate by URL
    seen = set()
    unique = []
    for call in api_calls:
        if call["url"] not in seen:
            seen.add(call["url"])
            unique.append(call)

    return unique


def extract_graphql_queries(html: str) -> list[dict[str, Any]]:
    """Extract GraphQL query patterns from HTML/JS."""
    queries = []

    # Pattern: gql`...` or graphql(`...`)
    gql_patterns = re.finditer(
        r"(?:gql|graphql)\s*`([^`]+)`",
        html,
    )
    for m in gql_patterns:
        queries.append({"type": "gql_tagged", "query": m.group(1).strip()[:200]})

    # Pattern: "query" or "mutation" in JSON configs
    query_patterns = re.finditer(
        r'["\'](?:query|mutation|subscription)["\']\s*:\s*["\']([^"\']+)["\']',
        html,
    )
    for m in query_patterns:
        queries.append({"type": "inline", "query": m.group(1)[:200]})

    return queries


def extract_json_ld(html: str) -> list[dict[str, Any]]:
    """Extract JSON-LD structured data from <script type="application/ld+json">."""
    ld_patterns = re.finditer(
        r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    results = []
    for m in ld_patterns:
        try:
            data = json.loads(m.group(1).strip())
            results.append(data)
        except (json.JSONDecodeError, ValueError):
            logger.warning("json_ld_parse_failed")
    return results


def _parse_braced_json(text: str, start: int) -> dict[str, Any] | None:
    """Parse a JSON object starting at text[start] using brace counting."""
    if start < 0 or text[start] != "{":
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed: Any = json.loads(text[start : i + 1])
                    if isinstance(parsed, dict):
                        return parsed
                    return None
                except json.JSONDecodeError:
                    return None
    return None


def extract_nextjs_props(html: str) -> dict[str, Any] | None:
    """Extract Next.js __NEXT_DATA__ props."""
    m = re.search(r"window\.__NEXT_DATA__\s*=\s*(\{)", html, re.DOTALL)
    if m:
        return _parse_braced_json(html, m.start(1))
    return None


def extract_nuxt_state(html: str) -> dict[str, Any] | None:
    """Extract Nuxt/Vue __NUXT__ state."""
    m = re.search(r"window\.__NUXT__\s*=\s*(\{)", html, re.DOTALL)
    if m:
        return _parse_braced_json(html, m.start(1))
    return None
