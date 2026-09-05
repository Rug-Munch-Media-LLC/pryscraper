"""EPA (ECHO enforcement case search) source for ``compliance_data.enforcement``.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from datasets.compliance_data._enforcement_data import _ECHO_CASE_URL
from datasets.compliance_data._enforcement_helpers import (
    _as_text,
    _mmddyyyy_date,
    _normalize_date,
    _sort_records,
)
from datasets.compliance_data._enforcement_transport import _fetch_json


def _map_epa(raw: dict[str, Any]) -> dict[str, Any]:
    """Map an ECHO enforcement-case object onto the canonical search record."""
    case_number = _as_text(raw.get("caseNumber"))
    title = _as_text(raw.get("caseName")) or _as_text(raw.get("respondent"))
    amount = (
        _as_text(raw.get("settledAmount"))
        or _as_text(raw.get("civilAmount"))
        or _as_text(raw.get("criminalAmount"))
    )
    return {
        "agency": "epa",
        "id": f"epa:{case_number}" if case_number else None,
        "title": title or f"EPA enforcement case {case_number or 'unknown'}",
        "type": _as_text(raw.get("caseType")) or "EPA Enforcement Case",
        "company": _as_text(raw.get("respondent")),
        "date": _mmddyyyy_date(_as_text(raw.get("filingDate")))
        or _normalize_date(_as_text(raw.get("filingDate"))),
        "penalty_amount": amount,
        "url": (
            f"https://echo.epa.gov/enforcement-case-summary?case_num={quote(case_number)}"
            if case_number
            else None
        ),
        "source": "echo.epa.gov",
    }


async def _fetch_epa(query: str, limit: int) -> list[dict[str, Any]]:
    """EPA enforcement case search via the free ECHO REST API (no key)."""
    params: dict[str, str] = {"output": "JSON", "p_pretty_print": "YES"}
    if query.strip():
        params["p_respondent"] = query.strip()
    payload = await _fetch_json(_ECHO_CASE_URL, params)
    if payload is None:
        return []
    results = payload.get("Results")
    if not isinstance(results, list):
        return []
    return _sort_records([_map_epa(raw) for raw in results if isinstance(raw, dict)], limit)


async def _get_epa_action(value: str) -> dict[str, Any]:
    payload = await _fetch_json(_ECHO_CASE_URL, {"output": "JSON", "p_case_number": value})
    if payload is None:
        return {}
    results = payload.get("Results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return {}
    mapped = _map_epa(results[0])
    return {
        "agency": "epa",
        "id": mapped["id"],
        "title": mapped["title"],
        "summary": None,
        "defendants": [mapped["company"]] if mapped["company"] else [],
        "penalties": (
            [{"type": "settlement", "amount": mapped["penalty_amount"]}]
            if mapped["penalty_amount"]
            else []
        ),
        "url": mapped["url"],
    }
