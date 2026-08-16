"""Scholarly search — OpenAlex (primary) + Crossref (fallback), both free.

OpenAlex (https://api.openalex.org) is a free, CC0-licensed catalog of
over 250M scholarly works with no API key required. Crossref
(https://api.crossref.org) is the DOI registration agency API, also free
and keyless. OpenAlex is tried first; if it fails or returns no results
the module falls back to Crossref. Both are "never raise" — any failure
degrades to ``[]`` / ``{}``.

Contract
--------
* :func:`search_papers` — async, never raises, returns a ``list``
  (``[]`` on failure). Full-text keyword search across scholarly works.
* :func:`get_paper` — async, never raises, returns a ``dict`` (``{}``
  on failure). Fetch one work by its OpenAlex id.

Result shapes
-------------
``search_papers`` returns a list of::

    {
        "id": "https://openalex.org/W2741809807",
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "year": 2017,
        "citations": 62342,
        "doi": "10.48550/arXiv.1706.03762",
        "url": "https://openalex.org/W2741809807",
        "source": "openalex",
    }

``get_paper`` returns the same shape plus a best-effort ``abstract``
(reconstructed from OpenAlex's inverted-index when present).

Free-API terms: OpenAlex is CC0 with a default 10 req/s limit; Crossref
is free with polite-pool usage encouraged. Backoff: 2 retries,
exponential (0.4s -> 1.6s).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import contextlib
import logging
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_OPENALEX_ROOT = "https://api.openalex.org"
_CROSSREF_ROOT = "https://api.crossref.org"
_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-research/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}
_MAX_LIMIT = 100


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _authors_of(authorships: Any) -> list[str]:
    """Extract author display names from OpenAlex ``authorships``."""
    if not isinstance(authorships, list):
        return []
    authors: list[str] = []
    for item in authorships:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        name = None
        if isinstance(author, dict):
            name = _as_text(author.get("display_name")) or _as_text(author.get("name"))
        name = name or _as_text(item.get("raw_author_name"))
        if name and name not in authors:
            authors.append(name)
    return authors


def _abstract_from_index(index: Any) -> str | None:
    """Reconstruct an abstract from OpenAlex's inverted index."""
    if not isinstance(index, dict) or not index:
        return None
    try:
        max_pos = max(int(p) for positions in index.values() for p in positions)
    except (TypeError, ValueError):
        return None
    words: list[str | None] = [None] * (max_pos + 1)
    for word, positions in index.items():
        for pos in positions:
            try:
                p = int(pos)
            except (TypeError, ValueError):
                continue
            if 0 <= p <= max_pos:
                words[p] = word
    text = " ".join(w for w in words if w is not None).strip()
    return text or None


def _map_openalex_work(raw: dict[str, Any]) -> dict[str, Any]:
    """Map an OpenAlex ``works`` object onto the canonical record."""
    openalex_id = _as_text(raw.get("id"))
    doi = _as_text(raw.get("doi"))
    if doi:
        doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    return {
        "id": openalex_id,
        "title": _as_text(raw.get("display_name")) or _as_text(raw.get("title")),
        "authors": _authors_of(raw.get("authorships")),
        "year": raw.get("publication_year")
        if isinstance(raw.get("publication_year"), int)
        else None,
        "citations": raw.get("cited_by_count")
        if isinstance(raw.get("cited_by_count"), int)
        else None,
        "doi": doi,
        "url": openalex_id,
        "source": "openalex",
    }


def _map_crossref_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a Crossref ``items`` entry onto the canonical record."""
    title = raw.get("title")
    title_text = _as_text(title[0]) if isinstance(title, list) and title else _as_text(title)
    authors: list[str] = []
    for author in raw.get("author", []):
        if not isinstance(author, dict):
            continue
        given = _as_text(author.get("given"))
        family = _as_text(author.get("family"))
        name = " ".join(part for part in (given, family) if part).strip() or _as_text(
            author.get("name")
        )
        if name and name not in authors:
            authors.append(name)
    year: int | None = None
    for key in ("published-print", "published-online", "issued"):
        parts = raw.get(key, {}).get("date-parts") if isinstance(raw.get(key), dict) else None
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            with contextlib.suppress(TypeError, ValueError):
                year = int(parts[0][0])
            if year:
                break
    doi = _as_text(raw.get("DOI"))
    return {
        "id": f"https://doi.org/{doi}" if doi else _as_text(raw.get("URL")),
        "title": title_text,
        "authors": authors,
        "year": year,
        "citations": raw.get("is-referenced-by-count")
        if isinstance(raw.get("is-referenced-by-count"), int)
        else None,
        "doi": doi,
        "url": _as_text(raw.get("URL")) or (f"https://doi.org/{doi}" if doi else None),
        "source": "crossref",
    }


async def _get_json(url: str, params: dict[str, str]) -> dict[str, Any] | None:
    """GET ``url`` and return its JSON object, or None on any failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"expected JSON object at {url}")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _openalex_search(query: str, limit: int) -> list[dict[str, Any]] | None:
    """OpenAlex works search; None on failure, [] when zero results."""
    payload = await _get_json(
        f"{_OPENALEX_ROOT}/works",
        {"search": query, "per-page": str(limit)},
    )
    if payload is None:
        return None
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [_map_openalex_work(raw) for raw in results if isinstance(raw, dict)]


async def _crossref_search(query: str, limit: int) -> list[dict[str, Any]] | None:
    """Crossref works search; None on failure, [] when zero results."""
    payload = await _get_json(
        f"{_CROSSREF_ROOT}/works",
        {"query": query, "rows": str(limit)},
    )
    if payload is None:
        return None
    message = payload.get("message")
    items = message.get("items") if isinstance(message, dict) else None
    if not isinstance(items, list):
        return []
    return [_map_crossref_item(raw) for raw in items if isinstance(raw, dict)]


# ── Public API ─────────────────────────────────────────────────────────
async def search_papers(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search scholarly works by keyword.

    Args:
        query: Search terms (e.g. ``"attention is all you need"``).
        limit: Max results to return (1-100).

    Returns:
        List of paper records (see module docstring), OpenAlex first with
        Crossref as fallback. ``[]`` on total failure. Never raises.
    """
    try:
        return await _search_papers(query, limit)
    except Exception:
        logger.exception("academic_search_crashed", extra={"query": query})
        return []


async def _search_papers(query: str, limit: int) -> list[dict[str, Any]]:
    text = (query or "").strip()
    if not text:
        return []
    limit = max(1, min(int(limit), _MAX_LIMIT))
    openalex = await _openalex_search(text, limit)
    if openalex:
        return openalex
    if openalex is not None:
        # OpenAlex responded with zero results — still try Crossref before
        # giving up (its relevance ranking differs and may surface matches).
        pass
    crossref = await _crossref_search(text, limit)
    return crossref or []


async def get_paper(openalex_id: str) -> dict[str, Any]:
    """Fetch one scholarly work by its OpenAlex id.

    Args:
        openalex_id: OpenAlex id, with or without the
            ``https://openalex.org/`` prefix (e.g. ``"W2741809807"``).

    Returns:
        Paper record (see module docstring) plus best-effort ``abstract``,
        or ``{}`` on failure (unknown id, network error). Never raises.
    """
    try:
        return await _get_paper(openalex_id)
    except Exception:
        logger.exception("academic_get_paper_crashed", extra={"openalex_id": openalex_id})
        return {}


async def _get_paper(openalex_id: str) -> dict[str, Any]:
    raw_id = (openalex_id or "").strip()
    if not raw_id:
        return {}
    raw_id = raw_id.replace("https://openalex.org/", "").replace("http://openalex.org/", "")
    payload = await _get_json(f"{_OPENALEX_ROOT}/works/{raw_id}", {})
    if payload is None:
        return {}
    record = _map_openalex_work(payload)
    if record.get("id") is None:
        return {}
    record["abstract"] = _abstract_from_index(payload.get("abstract_inverted_index"))
    return record
