"""Government contract bidding data — solicitations + awards, multi-source.

Aggregates free, no-auth (or free-key) sources of public contract
opportunities for the highest-value B2B procurement niche:

* **SAM.gov** — federal solicitations / awards. Reuses
  :mod:`gov_data.procurement` when it is present in this tree (it already
  wraps the free SAM.gov Opportunities API v2); otherwise falls back to the
  same API directly (key ``PRY_SAM_API_KEY``, free at
  https://sam.gov/content/webservices).
* **TED** (EU) — the European Union's Tenders Electronic Daily. Free public
  search API, no auth: https://api.ted.europa.eu/v3/notices/search.
* **NY State Contract Reporter** — one well-documented state portal
  (``nycr.ny.gov``). Public JSON search, no auth. Best-effort.
* **FedConnect** — federal "public opportunities" search. Best-effort HTML
  parse (FedConnect has no documented JSON API; may return ``[]``).

Contract
--------
* :func:`search_contracts` — async, never raises, returns a ``list``
  (``[]`` on failure). Merges all four sources, newest due-date first.
* :func:`get_contract` — async, never raises, returns a ``dict`` (``{}``
  on failure). Fetches one record by its source-prefixed id
  (``sam:`` / ``ted:`` / ``ny:`` / ``fedconnect:``; bare ids default to
  SAM.gov).

Result shapes
-------------
``search_contracts`` returns a list of:

    {
        "id": "sam:3488234",
        "title": "Z--TEST Presolicitation",
        "agency": "DEPT OF THE AIR FORCE",
        "type": "solicitation",          # "solicitation" | "award"
        "notice_type": "Presolicitation",
        "naics": "336411",
        "set_aside": "Total Small Business Set-Aside (FAR 19.5)",
        "due_date": "2026-01-01 12:00:00+00",
        "award_date": None,
        "value": None,
        "url": "https://sam.gov/opp/3488234/view",
        "source": "sam_gov",
    }

``get_contract`` returns a richer detail record (``{}`` when the id does
not exist) with ``description``, ``contacts`` and ``attachments``.

Free-API terms: SAM.gov v2 caps page size at 200; TED and NYSCR are free
public endpoints without documented hard rate limits. Backoff: 2 retries,
exponential (0.4s -> 1.6s) for the HTTPError retryable family.

Implementation lives in :mod:`contracts_common` (constants + shared
helpers), :mod:`contracts_parsers` (payload mappers) and
:mod:`contracts_fetchers` (source fetchers); this module is a thin
re-export facade.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
from typing import Any

from datasets.bidding_data.contracts_common import (  # noqa: F401
    _API_KEY_ENV,
    _FEDCONNECT_BASE,
    _HEADERS,
    _NY_BASE,
    _NY_DETAIL_BASE,
    _RETRY_CONFIG,
    _SAM_BASE,
    _SAM_MAX_LIMIT,
    _TED_BASE,
    _TED_DETAIL_BASE,
    _TIMEOUT,
    _as_text,
    _canonical_type,
    _fetch_json,
    _fetch_text,
    _gov_data_procurement,
    _gov_procurement,
    _sort_by_due_date,
)
from datasets.bidding_data.contracts_fetchers import (  # noqa: F401
    _fedconnect_get,
    _fedconnect_records,
    _ny_get,
    _ny_records,
    _sam_api_key,
    _sam_direct_records,
    _sam_get,
    _sam_records,
    _ted_get,
    _ted_records,
)
from datasets.bidding_data.contracts_parsers import (  # noqa: F401
    _FEDCONNECT_LINK_RE,
    _FEDCONNECT_TITLE_RE,
    _fedconnect_map,
    _ny_map,
    _sam_map,
    _ted_map,
)

logger = logging.getLogger(__name__)


# ── Public API ─────────────────────────────────────────────────────────
async def search_contracts(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search contract solicitations + awards across all free sources.

    Args:
        query: Keyword search string (e.g. ``"aircraft maintenance"``).
        limit: Max results to return (1-200; each source is capped at 200).

    Returns:
        A list of contract records (see module docstring), merged across
        SAM.gov, TED, NY Contract Reporter and FedConnect, sorted by due
        date ascending (soonest first; records without a due date last).
        ``[]`` on failure. Never raises.
    """
    try:
        return await _search_contracts(query, limit)
    except Exception:
        logger.exception("bidding_contracts_search_crashed", extra={"query": query})
        return []


async def _search_contracts(query: str, limit: int) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    capped = max(1, min(int(limit), 200))
    chunks = await asyncio.gather(
        _sam_records(query, capped),
        _ted_records(query, capped),
        _ny_records(query, capped),
        _fedconnect_records(query, capped),
    )
    records = [record for chunk in chunks for record in chunk if isinstance(record, dict)]
    return _sort_by_due_date(records, capped)


async def get_contract(contract_id: str) -> dict[str, Any]:
    """Fetch one contract by its source-prefixed id.

    Args:
        contract_id: e.g. ``"sam:3488234"``, ``"ted:123456-2026"``,
            ``"ny:42"``, ``"fedconnect:FA1234"``. Bare ids default to
            SAM.gov.

    Returns:
        Contract detail record (see module docstring) or ``{}`` on failure
        (unknown id, source error, network error). Never raises.
    """
    try:
        return await _get_contract(contract_id)
    except Exception:
        logger.exception("bidding_contracts_get_crashed", extra={"contract_id": contract_id})
        return {}


async def _get_contract(contract_id: str) -> dict[str, Any]:
    cid = str(contract_id or "").strip()
    if not cid:
        return {}
    prefix, sep, rest = cid.partition(":")
    if sep:
        if prefix == "sam":
            return await _sam_get(rest)
        if prefix == "ted":
            return await _ted_get(rest)
        if prefix == "ny":
            return await _ny_get(rest)
        if prefix == "fedconnect":
            return await _fedconnect_get(rest)
        logger.warning("bidding_contracts_unknown_prefix", extra={"prefix": prefix})
        return {}
    # Bare numeric ids default to SAM.gov (largest federal source).
    return await _sam_get(cid)


__all__ = [
    "get_contract",
    "search_contracts",
]
