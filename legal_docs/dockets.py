"""U.S. federal/state docket search — free CourtListener REST API v4.

CourtListener (free.law) publishes the RECAP / PACER docket database through
a public REST API. Anonymous access is rate-limited; a free API token can be
set via the ``PRY_COURTLISTENER_API_KEY`` env var and is sent as
``Authorization: Token <key>``. Without a token the API currently returns
401, which degrades every function to ``{}`` / ``[]`` (never raises) — the
module still works fully when a token is configured.

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

Contract
--------
* :func:`search_dockets` — async, never raises, returns a ``list`` (``[]``
  on failure). Searches dockets by full-text ``query``.
* :func:`get_docket` — async, never raises, returns a ``dict`` (``{}`` on
  failure). Fetches one docket by its CourtListener integer id; when the id
  is a Justia-style slug (non-numeric) it falls back to a Justia docket-page
  scrape for metadata.

Result shapes
-------------
``search_dockets`` returns a list of:

    {
        "id": 123456,
        "case_name": "United States v. Example Corp.",
        "docket_number": "1:22-cv-00001",
        "court": "dcd",                    # CourtListener court code
        "date_filed": "2022-01-15",
        "date_terminated": None,
        "nature_of_suit": "Contract",
        "cause": None,
        "url": "https://www.courtlistener.com/docket/123456/",
        "source": "courtlistener",
    }

``get_docket`` returns the same fields plus ``description``,
``jury_demand``, ``jurisdiction_type``, ``date_argued``,
``date_reargued``, ``date_last_filing``, ``appeal_from`` and ``panel``.

Free-API terms: https://www.courtlistener.com/api/rest/v4/ — identify
yourself with a descriptive User-Agent. Backoff: 2 retries, exponential
(0.4s -> 1.6s).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import html
import logging
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
_JUSTIA_BASE = "https://dockets.justia.com"
_PACER_FETCH_URL = f"{_BASE_URL}/pacer-fetch/"
_NY_ECOURTS_URL = "https://iapps.courts.state.ny.us/webcivil/FCASSearch"
_TIMEOUT = httpx.Timeout(15.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pryscraper-legal/1.0; +https://git.rugmunch.io/RugMunchMedia/pryscraper)",
    "Accept": "application/json",
}

# Optional free token: https://www.courtlistener.com/accounts/register/
_API_KEY_ENV = "PRY_COURTLISTENER_API_KEY"

# Justia docket search results are signature-parsed (no anti-bot JSON); the
# page may change layout, in which case extraction degrades to [].
_JUSTIA_SEARCH_RE = re.compile(
    r'<a\s+href="(/docket/[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_JUSTIA_BLOCK_RE = re.compile(
    r'<div[^>]*class="[^"]*(?:case-block|case-info|docket)[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_JUSTIA_FIELD_RE = {
    # A capitalized phrase ending in Court/Circuit/District, optionally
    # "… of <place>" (e.g. "Southern District of New York").
    "court": re.compile(r"((?:[A-Z][A-Za-z]+ ){1,4}(?:Court|Circuit|District)(?: of [A-Za-z ]+)?)"),
    "docket_number": re.compile(r"(\d{1,2}:\d{2}-[a-z]{2}-\d{3,5})", re.IGNORECASE),
    "date_filed": re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
}
_JUSTIA_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_JUSTIA_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# NY eCourts civil case search (https://iapps.courts.state.ny.us/webcivil/).
# The results page renders a table of matching cases; rows are signature-
# parsed (the page may change layout, in which case extraction degrades to
# []). An index number looks like "651256/2023".
_NY_ECOURTS_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*data[^"]*"[^>]*>(.*?)</tr>', re.IGNORECASE | re.DOTALL
)
_NY_ECOURTS_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_NY_INDEX_RE = re.compile(r"\b(\d{3,6}/\d{4})\b")
# The webcivil civil-case search form fields (documented by NY courts; the
# query is placed in ``defendant`` for free-text name search and in
# ``index_number`` for the docket lookup path).
_NY_ECOURTS_FORM: dict[str, str] = {
    "param": "primary",
    "idx": "0",
    "court_type": "CIV",
    "court_type_1": "ALL",
    "case_type": "Civil",
    "case_status": "ALL",
    "filing_date": "",
    "filing_date1": "",
    "docket_number": "",
    "plaintiff": "",
    "defendant": "",
    "judge": "",
    "index_number": "",
    "submit": "Search",
}


def _headers() -> dict[str, str]:
    """Base request headers plus the CourtListener token when configured."""
    token = os.environ.get(_API_KEY_ENV, "").strip()
    if token:
        return {**_HEADERS, "Authorization": f"Token {token}"}
    return dict(_HEADERS)


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    """Coerce a JSON value to int/None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_docket(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a CourtListener v4 docket object onto the canonical record."""
    docket_id = _as_int(raw.get("id"))
    url = f"https://www.courtlistener.com/docket/{docket_id}/" if docket_id else None
    return {
        "id": docket_id,
        "case_name": _as_text(raw.get("case_name")),
        "docket_number": _as_text(raw.get("docket_number")),
        "court": _as_text(raw.get("court")),
        "date_filed": _as_text(raw.get("date_filed")),
        "date_terminated": _as_text(raw.get("date_terminated")),
        "nature_of_suit": _as_text(raw.get("nature_of_suit")),
        "cause": _as_text(raw.get("cause")),
        "url": url,
        "source": "courtlistener",
    }


def _map_docket_detail(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a full CourtListener v4 docket object (detail view) — superset of :func:`_map_docket`."""
    record = _map_docket(raw)
    record.update(
        {
            "description": _as_text(raw.get("description")),
            "jury_demand": _as_text(raw.get("jury_demand")),
            "jurisdiction_type": _as_text(raw.get("jurisdiction_type")),
            "date_argued": _as_text(raw.get("date_argued")),
            "date_reargued": _as_text(raw.get("date_reargued")),
            "date_last_filing": _as_text(raw.get("date_last_filing")),
            "appeal_from": _as_text(raw.get("appeal_from")),
            "panel": _as_text(raw.get("panel")),
        }
    )
    return record


def _map_recap(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a CourtListener v4 search-API docket hit (RECAP archive) onto the canonical record.

    The ``/search/`` endpoint uses camelCase field names and returns a
    ``source`` facet (``RECAP`` / ``PACER``) instead of the docket's own
    fields; normalize both naming conventions here.
    """
    docket_id = _as_int(raw.get("id"))
    url = _as_text(raw.get("absoluteURL"))
    if not url and docket_id:
        url = f"https://www.courtlistener.com/docket/{docket_id}/"
    return {
        "id": docket_id,
        "case_name": _as_text(raw.get("caseName") or raw.get("case_name")),
        "docket_number": _as_text(raw.get("docketNumber") or raw.get("docket_number")),
        "court": _as_text(raw.get("court") or raw.get("court_id")),
        "date_filed": _as_text(raw.get("dateFiled") or raw.get("date_filed")),
        "date_terminated": _as_text(raw.get("dateTerminated") or raw.get("date_terminated")),
        "nature_of_suit": _as_text(raw.get("natureOfSuit") or raw.get("suitNature")),
        "cause": _as_text(raw.get("cause")),
        "url": url,
        "source": "recap",
    }


def _strip_tags(text: str) -> str:
    """Strip HTML tags into plain text (Justia scrape helper)."""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _justia_url(link: str) -> str:
    """Resolve a Justia docket link to an absolute URL."""
    if link.startswith("http"):
        return link
    return f"{_JUSTIA_BASE}{link}"


def _justia_docket_id(url: str) -> str | None:
    """Last path segment of a Justia docket URL (used as a stable id)."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def _map_justia_search(
    name: str,
    link: str,
    block_text: str,
) -> dict[str, Any]:
    """Build a canonical record from a Justia search-result block."""
    url = _justia_url(link)
    docket_number = None
    court = None
    date_filed = None
    # Run field regexes over the tag-stripped block text so court names are
    # not matched inside href slugs (e.g. "...-southern-district-court-...").
    clean = _strip_tags(block_text)
    match = _JUSTIA_FIELD_RE["docket_number"].search(clean)
    if match:
        docket_number = match.group(1)
    match = _JUSTIA_FIELD_RE["court"].search(clean)
    if match:
        court = _strip_tags(match.group(1))
    match = _JUSTIA_FIELD_RE["date_filed"].search(clean)
    if match:
        date_filed = match.group(1)
    return {
        "id": _justia_docket_id(url),
        "case_name": _strip_tags(name),
        "docket_number": docket_number,
        "court": court,
        "date_filed": date_filed,
        "date_terminated": None,
        "nature_of_suit": None,
        "cause": None,
        "url": url,
        "source": "justia",
    }


def _parse_justia_search(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Signature-parse a Justia dockets search page into canonical records."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Prefer per-result blocks; fall back to bare link+text pairs.
    blocks = _JUSTIA_BLOCK_RE.findall(html_text) or [
        f'<a href="{link}">{name}</a>' for link, name in _JUSTIA_SEARCH_RE.findall(html_text)
    ]
    for block in blocks:
        if len(records) >= limit:
            break
        match = _JUSTIA_SEARCH_RE.search(block)
        if not match:
            continue
        link, name = match.group(1), match.group(2)
        if not name or not link:
            continue
        url = _justia_url(link)
        if url in seen:
            continue
        seen.add(url)
        record = _map_justia_search(name, link, block)
        if record["case_name"]:
            records.append(record)
    return records[:limit]


def _parse_justia_docket(html_text: str, slug: str) -> dict[str, Any]:
    """Signature-parse a Justia docket page for docket metadata.

    Best-effort: extracts case name (h1/title), docket number, court and
    the earliest date found. Fields Justia does not expose are left ``None``.
    """
    name: str | None = None
    match = _JUSTIA_H1_RE.search(html_text)
    if match:
        name = _strip_tags(match.group(1))
    if not name:
        match = _JUSTIA_TITLE_RE.search(html_text)
        if match:
            title = _strip_tags(match.group(1))
            name = title.split(" - ")[0] if title else None
    docket_number = None
    match = _JUSTIA_FIELD_RE["docket_number"].search(html_text)
    if match:
        docket_number = match.group(1)
    court = None
    match = _JUSTIA_FIELD_RE["court"].search(html_text)
    if match:
        court = _strip_tags(match.group(1))
    date_filed = None
    match = _JUSTIA_FIELD_RE["date_filed"].search(html_text)
    if match:
        date_filed = match.group(1)
    url = f"{_JUSTIA_BASE}/docket/{slug}"
    return {
        "id": slug,
        "case_name": name,
        "docket_number": docket_number,
        "court": court,
        "date_filed": date_filed,
        "date_terminated": None,
        "nature_of_suit": None,
        "cause": None,
        "url": url,
        "description": None,
        "jury_demand": None,
        "jurisdiction_type": None,
        "date_argued": None,
        "date_reargued": None,
        "date_last_filing": None,
        "appeal_from": None,
        "panel": None,
        "source": "justia",
    }


async def _fetch_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return the parsed JSON object, or ``None`` on failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("courtlistener payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_text(url: str, params: dict[str, Any] | None = None) -> str | None:
    """GET ``url`` and return the response text, or ``None`` on failure.

    Used by the Justia scrape path; HTML pages are returned as text and
    parsed with signature regexes (degrades to ``[]`` on layout changes).
    """

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


async def _fetch_json_post(url: str, body: dict[str, Any]) -> dict[str, Any] | None:
    """POST JSON ``body`` to ``url`` and return the parsed object, or ``None``.

    Used by the CourtListener ``pacer-fetch`` path (PACER docket lookup).
    """

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("courtlistener pacer-fetch payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_text_post(url: str, data: dict[str, str]) -> str | None:
    """POST form-encoded ``data`` to ``url`` and return the response text.

    Used by the NY eCourts scrape path; HTML pages are returned as text and
    parsed with signature regexes (degrades to ``None`` on failure).
    """

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_headers(), follow_redirects=True
        ) as client:
            response = await client.post(url, data=data)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


async def _fetch_pacer_docket(docket_id: int) -> dict[str, Any] | None:
    """POST to CourtListener's ``pacer-fetch`` endpoint (PACER docket lookup).

    Triggers a PACER fetch for a CourtListener ``docket_id`` that is missing
    from the RECAP archive. Requires the free API token with the
    ``pacer_fetch`` permission; degrades to ``None`` on failure.
    """
    return await _fetch_json_post(_PACER_FETCH_URL, {"docket_id": docket_id})


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
        A list of docket records (see module docstring). ``[]`` on failure
        (401 without a token, network error, bad payload). Never raises.
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


# ── NY eCourts (state civil) source ────────────────────────────────────
def _ny_date(value: str | None) -> str | None:
    """Normalize a NY eCourts ``MM/DD/YYYY`` filing date to ``YYYY-MM-DD``."""
    if not value:
        return None
    text = value.strip()
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if match:
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return text or None


def _parse_ny_ecourts(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Signature-parse the NY eCourts civil case-search results table.

    Each result row exposes the index number, case type, filing date, judge,
    plaintiff(s) and defendant(s). Parsing is best-effort: layout changes
    degrade to ``[]``.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _NY_ECOURTS_ROW_RE.findall(html_text):
        if len(records) >= limit:
            break
        cells = [
            cell
            for cell in (_strip_tags(cell) for cell in _NY_ECOURTS_CELL_RE.findall(row))
            if cell
        ]
        index_number: str | None = None
        idx = 0
        for pos, cell in enumerate(cells):
            match = _NY_INDEX_RE.search(cell)
            if match:
                index_number = match.group(1)
                idx = pos
                break
        if not index_number or index_number in seen:
            continue
        seen.add(index_number)
        # eCourts rows are: index number, case type, filing date, [judge],
        # plaintiff(s), defendant(s). The judge cell is often "&nbsp;" and
        # gets dropped, so anchor on the index cell for type/date and take
        # plaintiff/defendant from the last two cells.
        case_type = cells[idx + 1] if idx + 1 < len(cells) else None
        filing_date = _ny_date(cells[idx + 2] if idx + 2 < len(cells) else None)
        plaintiff = cells[-2] if len(cells) >= 5 else None
        defendant = cells[-1] if len(cells) >= 5 else None
        case_name = defendant or plaintiff or f"NY eCourts docket {index_number}"
        records.append(
            {
                "id": index_number,
                "case_name": case_name,
                "docket_number": index_number,
                "court": "New York State Supreme Court (Civil)",
                "date_filed": filing_date,
                "date_terminated": None,
                "nature_of_suit": case_type,
                "cause": None,
                "url": f"{_NY_ECOURTS_URL}?index_number={quote(index_number)}",
                "source": "state_ny",
            }
        )
    return records[:limit]


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
        Full docket record (see module docstring) or ``{}`` on failure
        (unknown id -> 404, network error, 401 without token). Never raises.
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
