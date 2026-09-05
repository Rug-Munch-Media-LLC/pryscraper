"""Per-agency enforcement source data registries for ``compliance_data``.

Loads the co-located ``enforcement.json`` and exposes the endpoint URLs,
agency list, fallback chain, timeout/retry policy and HTTP headers used
by the enforcement transport and per-agency modules.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from pry.engine.retry import RetryConfig

_DATA: dict[str, Any] = json.loads((Path(__file__).with_name("enforcement.json")).read_text())

_ENDPOINTS: dict[str, Any] = _DATA["endpoints"]
_FDA_ENDPOINTS: tuple[str, ...] = tuple(_ENDPOINTS["fda"])
_FTC_LIST_URL: str = _ENDPOINTS["ftc_list"]
_CFPB_SEARCH_URL: str = _ENDPOINTS["cfpb_search"]
_SEC_ADMIN_URL: str = _ENDPOINTS["sec_admin"]
_SEC_FTS_URL: str = _ENDPOINTS["sec_fts"]
_ECHO_CASE_URL: str = _ENDPOINTS["epa_echo_case"]
_OSHA_EST_URL: str = _ENDPOINTS["osha_establishment"]
_OSHA_DETAIL_URL: str = _ENDPOINTS["osha_detail"]
_DOJ_API_URL: str = _ENDPOINTS["doj_press_releases"]

_MAX_LIMIT: int = int(_DATA["max_limit"])
_AGENCIES: tuple[str, ...] = tuple(_DATA["agencies"])
_VALID_AGENCIES = {"all", *_AGENCIES}
# Single-agency queries for the newer enforcement sources fall through the
# chain below so one provider being down never empties the answer.
_AGENCY_FALLBACK: dict[str, tuple[str, ...]] = {
    agency: tuple(chain) for agency, chain in _DATA["agency_fallback"].items()
}

_TIMEOUT = httpx.Timeout(float(_DATA["timeout_seconds"]))
_RETRY_CONFIG = RetryConfig(
    max_retries=int(_DATA["retry"]["max_retries"]),
    base_delay=float(_DATA["retry"]["base_delay"]),
    max_delay=float(_DATA["retry"]["max_delay"]),
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": str(_DATA["user_agent"]),
    "Accept": "application/json",
}
_HTML_HEADERS = {
    "User-Agent": _HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml",
}
