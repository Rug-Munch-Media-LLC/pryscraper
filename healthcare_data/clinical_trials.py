"""Clinical trials — clinicaltrials.gov API v2 (free, no auth).

The U.S. National Library of Medicine's clinicaltrials.gov exposes a free,
no-auth REST API v2 that this module queries directly:

* ``GET /api/v2/studies?query.term=...`` — keyword search.
* ``GET /api/v2/studies/{nctId}`` — one study by its NCT id.

Both return JSON with a ``protocolSection`` per study; this module maps that
onto a compact, stable record. The endpoints have no rate limits for
reasonable use and require no API key.

Contract
--------
* :func:`search_trials` — async, never raises, returns a ``list`` (``[]`` on
  failure). ``limit`` is clamped to 1-100.
* :func:`get_trial` — async, never raises, returns a ``dict`` (``{}`` on
  failure — unknown id, network error).

Result shape
------------
``search_trials`` returns a list of:

    {
        "nct_id": "NCT05966207",
        "title": "Individual Intervention of Cognitive Stimulation",
        "status": "Completed",
        "phase": "N/A",
        "conditions": ["Cognitive Dysfunction"],
        "sponsor": "Escola Superior de Enfermagem de Coimbra",
        "start_date": "2021-12-27",
        "locations": [{"facility": "...", "city": "Coimbra", "country": "Portugal"}],
    }

API terms: https://clinicaltrials.gov/api/gui. Backoff: 2 retries,
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

import logging
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-healthcare/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

_MAX_LIMIT = 100  # clinicaltrials.gov caps pageSize at 100

# Canonical enrollment/overall-status values → human labels.
_STATUS_LABELS: dict[str, str] = {
    "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
    "APPROVED_FOR_MARKETING": "Approved for marketing",
    "AVAILABLE": "Available",
    "COMPLETED": "Completed",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation",
    "NOT_YET_RECRUITING": "Not yet recruiting",
    "NO_LONGER_AVAILABLE": "No longer available",
    "RECRUITING": "Recruiting",
    "SUSPENDED": "Suspended",
    "TEMPORARILY_NOT_AVAILABLE": "Temporarily not available",
    "TERMINATED": "Terminated",
    "UNKNOWN_STATUS": "Unknown status",
    "WITHDRAWN": "Withdrawn",
}

# Canonical design-module phase values → human labels.
_PHASE_LABELS: dict[str, str] = {
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE1_PHASE2": "Phase 1/Phase 2",
    "PHASE2": "Phase 2",
    "PHASE2_PHASE3": "Phase 2/Phase 3",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NOT_APPLICABLE": "N/A",
    "NA": "N/A",
}


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_status(value: Any) -> str | None:
    """Map an API status enum onto a human label (or title-cased passthrough)."""
    raw = _as_text(value)
    if not raw:
        return None
    return _STATUS_LABELS.get(raw.upper(), raw.replace("_", " ").title())


def _normalize_phases(phases: Any) -> str | None:
    """Join design-module phase enums into a single readable string."""
    if not isinstance(phases, list):
        raw = _as_text(phases)
        if not raw:
            return None
        return _PHASE_LABELS.get(raw.upper(), raw.replace("_", " ").title())
    labels = [
        _PHASE_LABELS.get(str(p).upper(), str(p).replace("_", " ").title())
        for p in phases
        if _as_text(p)
    ]
    return " | ".join(labels) if labels else None


def _map_location(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map one contactsLocationsModule location object; None if empty."""
    loc: dict[str, Any] = {}
    for key, label in (
        ("facility", "facility"),
        ("city", "city"),
        ("state", "state"),
        ("country", "country"),
    ):
        text = _as_text(raw.get(key))
        if text:
            loc[label] = text
    return loc or None


def _map_study(raw: Any) -> dict[str, Any]:
    """Map a clinicaltrials.gov v2 study object onto the canonical record."""
    if not isinstance(raw, dict):
        return {
            "nct_id": None,
            "title": None,
            "status": None,
            "phase": None,
            "conditions": [],
            "sponsor": None,
            "start_date": None,
            "locations": [],
        }
    ps = raw.get("protocolSection")
    if not isinstance(ps, dict):
        return {
            "nct_id": _as_text(raw.get("nctId")),
            "title": None,
            "status": None,
            "phase": None,
            "conditions": [],
            "sponsor": None,
            "start_date": None,
            "locations": [],
        }
    ident = ps.get("identificationModule", {})
    status_mod = ps.get("statusModule", {})
    design = ps.get("designModule", {})
    conditions_mod = ps.get("conditionsModule", {})
    sponsor_mod = ps.get("sponsorCollaboratorsModule", {})
    contacts = ps.get("contactsLocationsModule", {})

    conditions = [_as_text(c) for c in (conditions_mod.get("conditions") or []) if _as_text(c)]
    locations = []
    for loc_raw in contacts.get("locations") or []:
        if isinstance(loc_raw, dict):
            loc = _map_location(loc_raw)
            if loc:
                locations.append(loc)

    lead_sponsor = sponsor_mod.get("leadSponsor")
    sponsor = _as_text(lead_sponsor.get("name")) if isinstance(lead_sponsor, dict) else None

    start_struct = status_mod.get("startDateStruct")
    start_date = _as_text(start_struct.get("date")) if isinstance(start_struct, dict) else None

    return {
        "nct_id": _as_text(ident.get("nctId")),
        "title": _as_text(ident.get("briefTitle")) or _as_text(ident.get("officialTitle")),
        "status": _normalize_status(status_mod.get("overallStatus")),
        "phase": _normalize_phases(design.get("phases")),
        "conditions": conditions,
        "sponsor": sponsor,
        "start_date": start_date,
        "locations": locations,
    }


async def _fetch_json(url: str, params: dict[str, str] | None = None) -> Any:
    """GET ``url`` and return parsed JSON, or ``None`` on failure."""

    async def _one() -> Any:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Public API ─────────────────────────────────────────────────────────
async def search_trials(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search clinical trials by keyword.

    Args:
        query: Keyword search (e.g. ``"alzheimer"``, ``"covid vaccine"``).
        limit: Max results to return (1-100, default 20).

    Returns:
        A list of trial records (see module docstring). ``[]`` on failure
        or empty query. Never raises.
    """
    try:
        return await _search_trials(query, limit)
    except Exception:
        logger.exception("health_trials_search_crashed", extra={"query": query, "limit": limit})
        return []


async def _search_trials(query: str, limit: int) -> list[dict[str, Any]]:
    if not query or not str(query).strip():
        logger.warning("health_trials_empty_query")
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    payload = await _fetch_json(
        _STUDIES_URL,
        {"query.term": str(query).strip(), "pageSize": str(clamped)},
    )
    if payload is None:
        return []
    studies = payload.get("studies") if isinstance(payload, dict) else None
    if not isinstance(studies, list):
        return []
    return [_map_study(raw) for raw in studies]


async def get_trial(nct_id: str) -> dict[str, Any]:
    """Fetch one clinical trial by its NCT id.

    Args:
        nct_id: e.g. ``"NCT05966207"`` (case-insensitive).

    Returns:
        Trial record (see module docstring) or ``{}`` on failure
        (unknown id, network error). Never raises.
    """
    try:
        return await _get_trial(nct_id)
    except Exception:
        logger.exception("health_trials_get_crashed", extra={"nct_id": nct_id})
        return {}


async def _get_trial(nct_id: str) -> dict[str, Any]:
    if not nct_id or not str(nct_id).strip():
        return {}
    identifier = str(nct_id).strip()
    if not identifier.upper().startswith("NCT"):
        logger.warning("health_trials_invalid_id", extra={"nct_id": nct_id})
        return {}
    payload = await _fetch_json(f"{_STUDIES_URL}/{identifier}")
    if payload is None:
        return {}
    record = _map_study(payload)
    return record if record.get("nct_id") else {}
