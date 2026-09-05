"""Regulatory & compliance monitoring — FDA / FTC / CFPB / SEC / EPA / OSHA / DOJ.

Thin loader for the enforcement dataset. Agency endpoints, the fallback
chain and retry policy live in the co-located ``enforcement.json``; the
per-agency parsers, mappers, fetch/get verbs and HTTP transport live in
``_enforcement_spec``. This module owns the (patchable) retry policy and
the public entry points.

Sources: openFDA enforcement (drug/food/device), FTC cases & proceedings
listing, CFPB consumer-complaints search API, SEC EDGAR full-text + AAER
admin proceedings, EPA ECHO enforcement cases, OSHA IMIS inspections and
DOJ press releases — all free, no-auth public sources. The newer agencies
form a fallback chain for single-agency queries (``epa`` → ``osha`` →
``doj``) so a provider being down never empties the answer;
``agency="all"`` merges every source, newest first.

Contract (all async, never raise):
* :func:`search_enforcement` → ``list`` (``[]`` on failure); ``agency``
  is ``"all"`` (default) or one of the seven agencies.
* :func:`get_action` → ``dict`` (``{}`` on failure); accepts the prefixed
  ids returned by :func:`search_enforcement` (``fda:<recall_number>`` /
  ``ftc:<slug>`` / ``cfpb:<complaint_id>`` / ``sec:<id>`` /
  ``epa:<case_number>`` / ``osha:<inspection_number>`` / ``doj:<slug>``).
* :func:`watch_company` → ``list`` of matches for a company (compliance
  screening); ``agencies`` is ``"all"`` or a comma-separated subset.

Search records carry exactly ``{agency, id, title, type, company, date,
penalty_amount, url}`` plus a ``source`` tag. ``penalty_amount`` is
``None`` unless an amount can be extracted from the underlying source
(EPA ECHO exposes settlement/civil/criminal amounts).

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

from datasets.compliance_data import _enforcement_spec as _spec
from pry.engine.retry import RetryConfig

logger = logging.getLogger(__name__)

_MAX_LIMIT = _spec._MAX_LIMIT
_AGENCIES = _spec._AGENCIES
_VALID_AGENCIES = _spec._VALID_AGENCIES
_AGENCY_FALLBACK = _spec._AGENCY_FALLBACK

# Patchable retry policy (tests set ``enforcement._RETRY_CONFIG``); the
# spec transport reads it through the bound getter at call time.
_RETRY_CONFIG = RetryConfig(
    max_retries=int(_spec._DATA["retry"]["max_retries"]),
    base_delay=float(_spec._DATA["retry"]["base_delay"]),
    max_delay=float(_spec._DATA["retry"]["max_delay"]),
    retryable_exceptions=(httpx.HTTPError,),
)

_spec.bind_retry(lambda: _RETRY_CONFIG)

_WATCH_FETCH: dict[str, Any] = {**_spec.FETCH_BY_AGENCY, "cfpb": _spec._fetch_cfpb_company}


# ── Public API ────────────────────────────────────────────────────────
async def search_enforcement(
    agency: str = "all", query: str = "", limit: int = 20
) -> list[dict[str, Any]]:
    """Search enforcement actions across the supported agencies.

    ``agency`` is ``"all"`` (default, merges every source newest-first)
    or one of the seven agencies; ``query`` is a keyword string (empty =
    recent actions); ``limit`` is capped at 1-100. Returns search records
    (see module docstring); ``[]`` on failure. Never raises.
    """
    try:
        return await _search_enforcement(agency, query, limit)
    except Exception:
        logger.exception(
            "compliance_enforcement_search_crashed", extra={"agency": agency, "query": query}
        )
        return []


async def _search_enforcement(agency: str, query: str, limit: int) -> list[dict[str, Any]]:
    normalized = str(agency).strip().lower()
    if normalized not in _VALID_AGENCIES:
        logger.warning("compliance_enforcement_invalid_agency", extra={"agency": agency})
        return []
    clamped = max(1, min(int(limit), _MAX_LIMIT))
    if normalized in _AGENCY_FALLBACK:
        # EPA → OSHA → DOJ fallback chain (see module docstring).
        for source in _AGENCY_FALLBACK[normalized]:
            records = await _spec.FETCH_BY_AGENCY[source](query, clamped)
            if records:
                return records
        return []
    if normalized != "all":
        return await _spec.FETCH_BY_AGENCY[normalized](query, clamped)
    merged: list[dict[str, Any]] = []
    for fetch in _spec.FETCH_BY_AGENCY.values():
        merged.extend(await fetch(query, clamped))
    return _spec._sort_records(_spec._dedupe_records(merged), clamped)


async def get_action(agency: str, id: str) -> dict[str, Any]:
    """Fetch one enforcement action by its prefixed id.

    ``agency`` is one of the seven agencies; ``id`` is a prefixed id
    returned by :func:`search_enforcement` (e.g. ``fda:D-1234``,
    ``sec:34-105834``). Returns action detail (see module docstring) or
    ``{}`` on failure. Never raises.
    """
    try:
        return await _get_action(agency, id)
    except Exception:
        logger.exception("compliance_enforcement_get_crashed", extra={"agency": agency, "id": id})
        return {}


async def _get_action(agency: str, action_id: str) -> dict[str, Any]:
    if not action_id or not str(action_id).strip():
        return {}
    normalized = str(agency).strip().lower()
    if normalized not in _AGENCIES:
        logger.warning("compliance_enforcement_unknown_agency", extra={"agency": agency})
        return {}
    rid = str(action_id).strip()
    prefix, _, value = rid.partition(":")
    if value:
        if prefix != normalized:
            # Mismatched prefix (e.g. cfpb:id requested as fda) → no match.
            logger.warning(
                "compliance_enforcement_prefix_mismatch",
                extra={"agency": agency, "id": action_id},
            )
            return {}
        rid = value
    return await _spec.GET_ACTION_BY_AGENCY[normalized](rid)


async def watch_company(company: str, agencies: str = "all") -> list[dict[str, Any]]:
    """Return enforcement/complaint matches for a specific company.

    Compliance screening: ``company`` is the name to screen; ``agencies``
    is ``"all"`` (default) or a comma-separated subset (``"fda,sec"``).
    Returns matching search records, newest first; ``[]`` on failure.
    Never raises.
    """
    try:
        return await _watch_company(company, agencies)
    except Exception:
        logger.exception("compliance_watch_company_crashed", extra={"company": company})
        return []


async def _watch_company(company: str, agencies: str) -> list[dict[str, Any]]:
    name = str(company).strip()
    if not name:
        return []
    records: list[dict[str, Any]] = []
    for agency in _spec._parse_agencies(agencies):
        records.extend(await _WATCH_FETCH[agency](name, _MAX_LIMIT))
    return _spec._sort_records(_spec._dedupe_records(records), _MAX_LIMIT)


__all__ = ["get_action", "search_enforcement", "watch_company"]
