"""Per-agency enforcement source logic for ``compliance_data.enforcement``.

Thin re-export facade. The implementation lives in the co-located
focused modules:

* ``_enforcement_data`` — ``enforcement.json`` registries (endpoints,
  agencies, fallback chain, timeout/retry policy, headers).
* ``_enforcement_transport`` — retry-bound JSON/HTML fetchers.
* ``_enforcement_helpers`` — value coercion, date normalization, HTML
  stripping, record sorting/dedup, agency-spec parsing.
* ``_enforcement_{fda,ftc,cfpb,sec,epa,osha,doj}`` — per-agency parsers,
  mappers and fetch/get verbs.

HTTP transport is injected by the thin loader (``enforcement.py``) via
:func:`bind_retry` so the retry policy stays patchable in one place.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from datasets.compliance_data._enforcement_cfpb import (
    _cfpb_detail as _cfpb_detail,
    _cfpb_hits as _cfpb_hits,
    _fetch_cfpb as _fetch_cfpb,
    _fetch_cfpb_company as _fetch_cfpb_company,
    _get_cfpb_action as _get_cfpb_action,
    _map_cfpb as _map_cfpb,
)
from datasets.compliance_data._enforcement_data import (
    _AGENCIES as _AGENCIES,
    _AGENCY_FALLBACK as _AGENCY_FALLBACK,
    _CFPB_SEARCH_URL as _CFPB_SEARCH_URL,
    _DATA as _DATA,
    _DOJ_API_URL as _DOJ_API_URL,
    _ECHO_CASE_URL as _ECHO_CASE_URL,
    _ENDPOINTS as _ENDPOINTS,
    _FDA_ENDPOINTS as _FDA_ENDPOINTS,
    _FTC_LIST_URL as _FTC_LIST_URL,
    _HEADERS as _HEADERS,
    _HTML_HEADERS as _HTML_HEADERS,
    _MAX_LIMIT as _MAX_LIMIT,
    _OSHA_DETAIL_URL as _OSHA_DETAIL_URL,
    _OSHA_EST_URL as _OSHA_EST_URL,
    _RETRY_CONFIG as _RETRY_CONFIG,
    _SEC_ADMIN_URL as _SEC_ADMIN_URL,
    _SEC_FTS_URL as _SEC_FTS_URL,
    _TIMEOUT as _TIMEOUT,
    _VALID_AGENCIES as _VALID_AGENCIES,
)
from datasets.compliance_data._enforcement_doj import (
    _doj_slug as _doj_slug,
    _fetch_doj as _fetch_doj,
    _get_doj_action as _get_doj_action,
    _map_doj as _map_doj,
)
from datasets.compliance_data._enforcement_epa import (
    _fetch_epa as _fetch_epa,
    _get_epa_action as _get_epa_action,
    _map_epa as _map_epa,
)
from datasets.compliance_data._enforcement_fda import (
    _fda_detail as _fda_detail,
    _fda_url as _fda_url,
    _fetch_fda as _fetch_fda,
    _get_fda_action as _get_fda_action,
    _map_fda as _map_fda,
)
from datasets.compliance_data._enforcement_ftc import (
    _fetch_ftc as _fetch_ftc,
    _filter_ftc_rows as _filter_ftc_rows,
    _ftc_company_from_title as _ftc_company_from_title,
    _get_ftc_action as _get_ftc_action,
    _map_ftc as _map_ftc,
    _parse_ftc_listing as _parse_ftc_listing,
)
from datasets.compliance_data._enforcement_helpers import (
    _as_text as _as_text,
    _dedupe_records as _dedupe_records,
    _mmddyyyy_date as _mmddyyyy_date,
    _normalize_date as _normalize_date,
    _parse_agencies as _parse_agencies,
    _sort_records as _sort_records,
    _strip_tags as _strip_tags,
)
from datasets.compliance_data._enforcement_osha import (
    _fetch_osha as _fetch_osha,
    _get_osha_action as _get_osha_action,
    _map_osha as _map_osha,
    _parse_osha_inspections as _parse_osha_inspections,
)
from datasets.compliance_data._enforcement_sec import (
    _fetch_sec as _fetch_sec,
    _fetch_sec_admin as _fetch_sec_admin,
    _fetch_sec_edgar as _fetch_sec_edgar,
    _filter_sec_rows as _filter_sec_rows,
    _get_sec_action as _get_sec_action,
    _map_sec_admin as _map_sec_admin,
    _map_sec_edgar as _map_sec_edgar,
    _parse_sec_admin as _parse_sec_admin,
)
from datasets.compliance_data._enforcement_transport import (
    _fetch_html as _fetch_html,
    _fetch_json as _fetch_json,
    _get_retry_config as _get_retry_config,
    bind_retry as bind_retry,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# ── Dispatch tables (agency → fetch/get verbs) ────────────────────────
FETCH_BY_AGENCY: dict[str, Callable[[str, int], Awaitable[list[dict[str, Any]]]]] = {
    "fda": _fetch_fda,
    "ftc": _fetch_ftc,
    "cfpb": _fetch_cfpb,
    "sec": _fetch_sec,
    "epa": _fetch_epa,
    "osha": _fetch_osha,
    "doj": _fetch_doj,
}

GET_ACTION_BY_AGENCY: dict[str, Callable[[str], Awaitable[dict[str, Any]]]] = {
    "fda": _get_fda_action,
    "ftc": _get_ftc_action,
    "cfpb": _get_cfpb_action,
    "sec": _get_sec_action,
    "epa": _get_epa_action,
    "osha": _get_osha_action,
    "doj": _get_doj_action,
}
