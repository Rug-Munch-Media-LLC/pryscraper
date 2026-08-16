"""IP patent search backed by Google Patents' free XHR query API.

Primary source: Google Patents ``/xhr/query`` endpoint
(https://patents.google.com/xhr/query?url=q%3D{query}) — a public, keyless
JSON API that powers the patents.google.com search UI. No API key, no
registration, no rate-limit header enforcement; be gentle and keep the
shared Pry httpx client.

The public entrypoints are async functions that never raise:

* :func:`search_patents` — query patents; returns a normalized list:

      {
          "patent_id": str,       # e.g. "US9012345B2"
          "title": str,
          "assignee": str,        # "" when unassigned
          "inventor": str,        # "" when absent
          "filing_date": str,     # ISO-8601, "" when unknown
          "grant_date": str,      # ISO-8601 for granted (kind-code B) docs
          "abstract": str,        # snippet/abstract text
          "url": str,             # https://patents.google.com/patent/{id}/en
      }

* :func:`get_patent` — single patent detail; same shape (abstract enriched
  from the patent detail page when available).

On any failure (HTTP error, timeout, malformed JSON, empty results) the
functions degrade to ``[]`` / ``{}`` and log — they never raise.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import html
import logging
import re
import urllib.parse
from typing import Any

import httpx

from client import get_client

logger = logging.getLogger(__name__)

PATENTS_QUERY_URL = "https://patents.google.com/xhr/query"
PATENTS_PAGE_URL = "https://patents.google.com/patent/{patent_id}/en"
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
MAX_LIMIT = 100

# US/EP kind code "B1"/"B2"/"B3" indicate a granted patent; Google Patents
# only exposes a single publication_date in the search API, so we treat it
# as the grant date for granted docs and leave it empty otherwise. A1/A2
# codes are pre-grant application publications.
_GRANT_RE = re.compile(r"[A-Z]{2}\d+B\d*$")


def _is_grant(patent_id: str) -> bool:
    return bool(_GRANT_RE.search(patent_id)) or patent_id.endswith(("B1", "B2", "B3"))


def _clean(value: Any) -> str:
    """Strip HTML entities / whitespace from a free-text patent field."""
    if value is None:
        return ""
    text = html.unescape(str(value))
    return re.sub(r"\s+", " ", text).strip()


def _build_search_url(query: str) -> str:
    encoded = urllib.parse.quote(query)
    return f"{PATENTS_QUERY_URL}?url=q%3D{encoded}&exp="


def _clamp_limit(limit: int) -> int:
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        return 20


def _normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Google Patents search result item."""
    patent = item.get("patent") or {}
    patent_id = _clean(patent.get("publication_number") or _id_from(item.get("id", "")))
    publication_date = _clean(patent.get("publication_date"))
    grant_date = publication_date if _is_grant(patent_id) else ""
    return {
        "patent_id": patent_id,
        "title": _clean(patent.get("title")),
        "assignee": _clean(patent.get("assignee")),
        "inventor": _clean(patent.get("inventor")),
        "filing_date": _clean(patent.get("filing_date")),
        "grant_date": grant_date,
        "abstract": _clean(patent.get("abstract") or patent.get("snippet")),
        "url": PATENTS_PAGE_URL.format(patent_id=patent_id),
    }


def _id_from(record_id: str) -> str:
    """Extract the bare publication number from an xhr id like 'patent/US123B2/en'."""
    match = re.match(r"patent/([^/]+)", record_id or "")
    return match.group(1) if match else _clean(record_id)


def _parse_search_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results") or {}
    items: list[dict[str, Any]] = []
    for cluster in results.get("cluster") or []:
        for item in cluster.get("result") or []:
            normalized = _normalize_result(item)
            if normalized["patent_id"]:
                items.append(normalized)
    return items


async def search_patents(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search patents via Google Patents' free XHR query JSON API.

    Args:
        query: Free-text patent query (title/abstract/assignee/inventor…).
        limit: Max results to return (clamped to 1-100).

    Returns:
        Normalized patent records; ``[]`` on any failure (never raises).
    """
    query = str(query or "").strip()
    if not query:
        return []
    limit = _clamp_limit(limit)
    try:
        client = await get_client()
        response = await client.get(
            _build_search_url(query),
            timeout=HTTP_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        items = _parse_search_payload(payload)
        logger.info(
            "google_patents_search",
            extra={"query": query, "results": len(items), "limit": limit},
        )
        return items[:limit]
    except (httpx.HTTPError, ValueError, TypeError, OSError) as exc:  # JSON decode + network
        logger.warning("google_patents_search_failed", extra={"query": query, "error": str(exc)})
        return []


async def get_patent(patent_id: str) -> dict[str, Any]:
    """Fetch a single patent by publication number (e.g. ``US9012345B2``).

    Uses the search endpoint with an exact-match query, then enriches the
    abstract from the patent detail page when available. Never raises —
    returns ``{}`` when the patent cannot be found.

    Args:
        patent_id: Google Patents publication number (without scheme/host).

    Returns:
        Normalized patent record (see :func:`search_patents`), ``{}`` on
        failure or no match.
    """
    patent_id = str(patent_id or "").strip()
    if not patent_id:
        return {}
    try:
        client = await get_client()
        wanted = patent_id.upper()
        response = await client.get(
            _build_search_url(patent_id),
            timeout=HTTP_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        for record in _parse_search_payload(response.json()):
            if record["patent_id"].upper() == wanted:
                record["abstract"] = (
                    await _fetch_abstract(client, record["patent_id"]) or record["abstract"]
                )
                return record
        logger.info("google_patents_not_found", extra={"patent_id": patent_id})
        return {}
    except (httpx.HTTPError, ValueError, TypeError, OSError) as exc:
        logger.warning(
            "google_patents_get_failed", extra={"patent_id": patent_id, "error": str(exc)}
        )
        return {}


async def _fetch_abstract(client: httpx.AsyncClient, patent_id: str) -> str:
    """Best-effort abstract extraction from the patent detail page."""
    try:
        response = await client.get(
            PATENTS_PAGE_URL.format(patent_id=patent_id),
            timeout=HTTP_TIMEOUT,
            headers={"Accept": "text/html"},
        )
        response.raise_for_status()
        text = response.text
        # Meta description is the abstract on patents.google.com detail pages.
        match = re.search(
            r'<meta\s+name="description"\s+content="([^"]+)"', text, flags=re.IGNORECASE
        )
        if match:
            return _clean(match.group(1))
    except (httpx.HTTPError, OSError):
        logger.debug("google_patents_abstract_failed", extra={"patent_id": patent_id})
    return ""
