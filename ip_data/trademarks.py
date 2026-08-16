"""US trademark search/detail via USPTO's free JSON APIs.

Primary sources (both official USPTO, keyless/free-tier):

* Trademark Search JSON — ``POST https://tmsearch.uspto.gov/api-v1-0-0/tmsearch``
  (Solr-style query API that powers the tmsearch.uspto.gov search UI).
* TSDR case-status JSON — ``GET https://tsdrapi.uspto.gov/ts/cd/casestatus/{serial}/info.json``
  (single-trademark detail; a free API key from account.uspto.gov is optional
  and read from the ``USPTO_API_KEY`` environment variable when present —
  never hardcoded).

The public entrypoints are async functions that never raise:

* :func:`search_trademarks` — query the trademark register; returns a
  normalized list:

      {
          "serial_no": str,        # e.g. "97774270"
          "mark": str,
          "owner": str,            # "" when unlisted
          "status": str,           # e.g. "Live/Pending" | "Live/Registered"
          "classes": list[str],    # international class numbers
          "registration_date": str,  # ISO-8601, "" when not yet registered
          "url": str,              # tmsearch.uspto.gov search URL for the serial
      }

* :func:`get_trademark` — single trademark detail by serial number; a flat
  dict of normalized fields (serial_no, mark, owner, status, filing_date,
  registration_date, classes, goods_services, url).

On any failure (HTTP error, timeout, non-JSON response, empty results) the
functions degrade to ``[]`` / ``{}`` and log — they never raise.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from client import get_client

logger = logging.getLogger(__name__)

TM_SEARCH_URL = "https://tmsearch.uspto.gov/api-v1-0-0/tmsearch"
TSDR_STATUS_URL = "https://tsdrapi.uspto.gov/ts/cd/casestatus/{serial}/info.json"
TM_DETAIL_URL = "https://tmsearch.uspto.gov/search/search-information?searchText={serial}"
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
MAX_LIMIT = 100


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _first(doc: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty string value among candidate keys."""
    for key in keys:
        value = doc.get(key)
        if value is not None and str(value) not in ("", "None", "null"):
            return _text(value)
    return ""


def _classes_from(doc: dict[str, Any]) -> list[str]:
    """Extract international class numbers from a Solr doc / TSDR payload."""
    classes: list[str] = []
    raw = doc.get("classifications")
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                num = _first(entry, "classNumber", "class", "internationalClassNumber")
            else:
                num = str(entry)
            if num:
                classes.append(num)
    elif isinstance(raw, dict):
        for key in ("classNumber", "class", "internationalClassNumber"):
            candidate = raw.get(key)
            if candidate is not None:
                classes.append(str(candidate))
    if not classes:
        raw = doc.get("internationalClasses")
        if isinstance(raw, list):
            classes = [_text(entry) for entry in raw if _text(entry)]
        elif raw:
            classes = [_text(raw)]
    # de-duplicate while preserving order
    return list(dict.fromkeys(classes))


def _serial_from(doc: dict[str, Any]) -> str:
    return _first(doc, "serialNumber", "serial_no", "serial", "applicationNumber")


def _clamp_limit(limit: int) -> int:
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        return 20


def _normalize_search_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Solr doc from the Trademark Search JSON API."""
    case_file = doc.get("caseFile") or {}
    serial_no = _serial_from(doc) or _serial_from(case_file)
    return {
        "serial_no": serial_no,
        "mark": _first(doc, "markIdentification", "mark", "wordMark", "markText")
        or _first(case_file, "mark", "markIdentification"),
        "owner": _first(doc, "partyName", "ownerName", "applicantName")
        or _first(case_file, "partyName", "ownerName"),
        "status": _first(doc, "status", "applicationStatus")
        or _first(case_file, "status", "applicationStatus"),
        "classes": _classes_from(doc) or _classes_from(case_file),
        "registration_date": _first(doc, "registrationDate", "registration_date")
        or _first(case_file, "registrationDate"),
        "url": TM_DETAIL_URL.format(serial=serial_no) if serial_no else "",
    }


async def search_trademarks(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search US trademarks via USPTO's Trademark Search JSON API.

    Args:
        query: Free-text trademark query (mark text, owner, serial…).
        limit: Max results to return (clamped to 1-100).

    Returns:
        Normalized trademark records; ``[]`` on any failure (never raises).
    """
    query = str(query or "").strip()
    if not query:
        return []
    limit = _clamp_limit(limit)
    body = {
        "query": {"bool": {"must": [{"match": {"_all": query}}]}},
        "start": 0,
        "rows": limit,
    }
    try:
        client = await get_client()
        response = await client.post(
            TM_SEARCH_URL,
            json=body,
            timeout=HTTP_TIMEOUT,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        response_docs = (payload.get("response") or {}).get("docs") or []
        items = [_normalize_search_doc(doc) for doc in response_docs]
        items = [item for item in items if item["serial_no"] or item["mark"]]
        logger.info(
            "uspto_tm_search",
            extra={"query": query, "results": len(items), "limit": limit},
        )
        return items[:limit]
    except (httpx.HTTPError, ValueError, TypeError, OSError) as exc:
        logger.warning("uspto_tm_search_failed", extra={"query": query, "error": str(exc)})
        return []


async def get_trademark(serial_no: str) -> dict[str, Any]:
    """Fetch one US trademark by serial number via the TSDR case-status API.

    An optional free USPTO API key (``USPTO_API_KEY`` env var) unlocks the
    full TSDR payload; without a key the endpoint returns a notice and this
    function degrades to ``{}``. Never raises.

    Args:
        serial_no: USPTO serial number (digits only, e.g. ``97774270``).

    Returns:
        Normalized trademark detail dict, ``{}`` on failure / no data.
    """
    serial_no = str(serial_no or "").strip()
    if not serial_no:
        return {}
    url = TSDR_STATUS_URL.format(serial=serial_no)
    api_key = os.getenv("USPTO_API_KEY", "").strip()
    if api_key:
        url = f"{url}?apikey={api_key}"
    try:
        client = await get_client()
        response = await client.get(
            url, timeout=HTTP_TIMEOUT, headers={"Accept": "application/json"}
        )
        response.raise_for_status()
        payload = response.json()
        doc = payload.get("response") if isinstance(payload.get("response"), dict) else payload
        if not isinstance(doc, dict) or not doc:
            logger.info("uspto_tsdr_empty", extra={"serial_no": serial_no})
            return {}
        return {
            "serial_no": _serial_from(doc) or serial_no,
            "mark": _first(doc, "mark", "markIdentification", "markText"),
            "owner": _first(doc, "ownerName", "partyName", "applicantName"),
            "status": _first(doc, "status", "applicationStatus"),
            "filing_date": _first(
                doc, "application Filing Date", "filingDate", "applicationFilingDate"
            ),
            "registration_date": _first(doc, "registrationDate", "registration_date"),
            "classes": _classes_from(doc),
            "goods_services": _first(doc, "goodAndServices", "goodsServices", "description"),
            "url": TM_DETAIL_URL.format(serial=serial_no),
        }
    except (httpx.HTTPError, ValueError, TypeError, OSError) as exc:
        logger.warning("uspto_tsdr_failed", extra={"serial_no": serial_no, "error": str(exc)})
        return {}
