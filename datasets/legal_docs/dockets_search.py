"""Docket search and lookup orchestration across the free sources.

Sources, in fallback order (a source is only consulted when the previous one
yields nothing, so one provider down never empties the answer):

1. **CourtListener dockets endpoint** — ``/api/rest/v4/dockets/`` (primary,
   ``source="courtlistener"``).
2. **RECAP search API** — ``/api/rest/v4/search/?q=...&type=docket`` (the
   full RECAP/PACER archive, ``source="recap"``; same free token).
3. **Justia dockets scrape** — ``dockets.justia.com`` (``source="justia"``;
   no key, no auth; signature-based HTML extraction, best-effort).
4. **NY eCourts civil search** — ``iapps.courts.state.ny.us/webcivil/FCASSearch``
   (``source="state_ny"``; no key, no auth; form POST + signature-based HTML
   extraction of the results table, best-effort).

``get_docket`` additionally consults CourtListener's **PACER docket lookup**
(``/api/rest/v4/pacer-fetch/``, ``source="pacer"``; same free token, requires
the ``pacer_fetch`` permission) between the CourtListener detail endpoint and
the Justia scrape, and falls through to the NY eCourts index-number lookup
when a non-numeric id is not a Justia slug.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import re
from typing import Any

from datasets.legal_docs.dockets_http import (
    _BASE_URL,
    _JUSTIA_BASE,
    _NY_ECOURTS_URL,
    _fetch_json,
    _fetch_pacer_docket,
    _fetch_text,
    _fetch_text_post,
)
from datasets.legal_docs.dockets_parsers import (
    _NY_ECOURTS_FORM,
    _map_docket,
    _map_docket_detail,
    _map_recap,
    _parse_justia_docket,
    _parse_justia_search,
    _parse_ny_ecourts,
)

logger = logging.getLogger(__name__)


# ── Public API ─────────────────────────────────────────────────────────
async def search_dockets(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search dockets by full-text query across multiple free sources.

    Sources are consulted in fallback order — CourtListener dockets,
    RECAP search API, Justia, then NY eCourts (state civil) — so one
    provider being down never empties the result. Results are deduplicated
    by docket URL/id.

    Args:
        query: Full-text search string (e.g. ``"bitcoin ethereum fraud"``).
        limit: Max results to return (1-100; API caps page size at 100).

    Returns:
        A list of docket records. ``[]`` on failure (401 without a token,
        network error, bad payload). Never raises.
    """
    try:
        return await _search_dockets(query, limit)
    except Exception:
        logger.exception("legal_dockets_search_crashed", extra={"query": query})
        return []


async def _search_dockets(query: str, limit: int) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    limit = max(1, min(int(limit), 100))

    results = await _search_courtlistener(query, limit)
    if results:
        return results

    results = await _search_recap(query, limit)
    if results:
        return results

    results = await _search_justia(query, limit)
    if results:
        return results

    return await _search_ny_ecourts(query, limit)


async def _search_courtlistener(query: str, limit: int) -> list[dict[str, Any]]:
    payload = await _fetch_json(
        f"{_BASE_URL}/dockets/",
        {"q": query.strip(), "page_size": limit},
    )
    if payload is None:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [_map_docket(raw) for raw in results if isinstance(raw, dict)]


async def _search_recap(query: str, limit: int) -> list[dict[str, Any]]:
    """RECAP/PACER archive search via the CourtListener v4 search API.

    The search endpoint's ``type=docket`` facet searches the full RECAP
    archive (more coverage than the curated ``/dockets/`` index) and uses
    the same free ``PRY_COURTLISTENER_API_KEY`` token.
    """
    payload = await _fetch_json(
        f"{_BASE_URL}/search/",
        {"q": query.strip(), "type": "docket", "page_size": limit},
    )
    if payload is None:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [_map_recap(raw) for raw in results if isinstance(raw, dict)]


async def _search_justia(query: str, limit: int) -> list[dict[str, Any]]:
    """Justia dockets search scrape (keyless, signature-based, best-effort)."""
    page = await _fetch_text(f"{_JUSTIA_BASE}/search", {"q": query.strip()})
    if not page:
        return []
    try:
        return _parse_justia_search(page, limit)
    except (re.error, ValueError, TypeError):
        logger.warning("legal_dockets_justia_parse_failed", extra={"query": query})
        return []


async def _search_ny_ecourts(query: str, limit: int) -> list[dict[str, Any]]:
    """NY eCourts civil case search (keyless form POST, best-effort).

    The query is matched against the defendant name — the free webcivil
    form only accepts one name field per request.
    """
    if not query.strip():
        return []
    data = dict(_NY_ECOURTS_FORM)
    data["defendant"] = query.strip()
    page = await _fetch_text_post(_NY_ECOURTS_URL, data)
    if not page:
        return []
    try:
        return _parse_ny_ecourts(page, limit)
    except (re.error, ValueError, TypeError):
        logger.warning("legal_dockets_ny_ecourts_parse_failed", extra={"query": query})
        return []


async def _lookup_ny_ecourts(index_number: str) -> dict[str, Any]:
    """NY eCourts civil lookup by index/docket number (last-resort fallback).

    Returns the full docket shape (detail fields ``None`` where eCourts does
    not expose them) or ``{}`` when the number is unknown.
    """
    value = str(index_number).strip().lstrip("/")
    if not value:
        return {}
    data = dict(_NY_ECOURTS_FORM)
    data["index_number"] = value
    page = await _fetch_text_post(_NY_ECOURTS_URL, data)
    if not page:
        return {}
    try:
        records = _parse_ny_ecourts(page, 1)
    except (re.error, ValueError, TypeError):
        logger.warning("legal_dockets_ny_ecourts_lookup_parse_failed", extra={"index": value})
        return {}
    if not records:
        return {}
    record = records[0]
    record.update(
        {
            "description": None,
            "jury_demand": None,
            "jurisdiction_type": None,
            "date_argued": None,
            "date_reargued": None,
            "date_last_filing": None,
            "appeal_from": None,
            "panel": None,
        }
    )
    return record


async def get_docket(docket_id: int | str) -> dict[str, Any]:
    """Fetch one docket by its CourtListener id (or a Justia slug).

    Args:
        docket_id: CourtListener docket id (int or numeric string) — falls
            back to a CourtListener PACER fetch when the RECAP archive is
            missing it. A non-numeric string is treated as a Justia docket
            slug (scrape fallback), then as a NY eCourts index number.

    Returns:
        Full docket record or ``{}`` on failure (unknown id -> 404, network
        error, 401 without token). Never raises.
    """
    try:
        return await _get_docket(docket_id)
    except Exception:
        logger.exception("legal_dockets_get_crashed", extra={"docket_id": docket_id})
        return {}


async def _get_docket(docket_id: int | str) -> dict[str, Any]:
    try:
        numeric = int(docket_id)
    except (TypeError, ValueError):
        numeric = None
    if numeric is not None:
        payload = await _fetch_json(f"{_BASE_URL}/dockets/{numeric}/")
        if payload is not None:
            return _map_docket_detail(payload)
        # PACER fallback: trigger a CourtListener pacer-fetch for the docket
        # (requires the ``pacer_fetch`` permission on the API token).
        pacer = await _fetch_pacer_docket(numeric)
        if pacer:
            record = _map_docket_detail(pacer)
            record["source"] = "pacer"
            return record
        logger.warning("legal_dockets_cl_miss", extra={"docket_id": numeric})
        return {}
    # Non-numeric: treat as a Justia docket slug and scrape metadata; when
    # that misses, fall through to the NY eCourts index-number lookup.
    slug = str(docket_id).strip().lstrip("/")
    if not slug:
        return {}
    page = await _fetch_text(f"{_JUSTIA_BASE}/docket/{slug}")
    if page:
        try:
            return _parse_justia_docket(page, slug)
        except (re.error, ValueError, TypeError):
            logger.warning("legal_dockets_justia_docket_parse_failed", extra={"slug": slug})
    return await _lookup_ny_ecourts(slug)
