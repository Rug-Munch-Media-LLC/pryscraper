"""Regulatory & compliance monitoring — FDA / FTC / CFPB / SEC / EPA / OSHA / DOJ.

Aggregates free, no-auth public sources for enforcement actions and
consumer complaints. Used for mandatory compliance spend / regulatory
screening workflows (e.g. ``watch_company`` before onboarding a vendor).

Sources
-------
* **FDA** — openFDA ``enforcement`` endpoints (drug, food, device):
  ``api.fda.gov``, free, no key. Recalls / market withdrawals with
  ``classification`` (Class I/II/III).
* **FTC** — ``ftc.gov`` legal-library "cases & proceedings" listing
  (HTML scrape of a stable Drupal views page; free, no auth).
* **CFPB** — consumer complaints search API (free, no key) at
  ``consumerfinance.gov/data-research/consumer-complaints/api``.
* **SEC** — EDGAR full-text search (``efts.sec.gov/LATEST/search-index``)
  plus the AAER / administrative-proceedings listing on ``sec.gov``.
* **EPA** — ECHO enforcement case search (``echo.epa.gov/rest/enforcement/
  case_search``; free, no key). Civil/criminal enforcement cases with
  respondent names and settlement amounts.
* **OSHA** — IMIS establishment inspections (``osha.gov/pls/imis/
  establishmentsearch.html``; free, no key; HTML scrape, best-effort).
* **DOJ** — press releases / actions (``justice.gov/api/v1/press_releases``;
  free, no key).

The three newer agencies form a fallback chain for single-agency queries:
``epa`` → ``osha`` → ``doj`` (i.e. a request for ``agency="epa"`` returns
OSHA/DOJ results when ECHO is down or empty) so a provider being down never
empties the answer. ``agency="all"`` merges every source, newest first.

Contract
--------
* :func:`search_enforcement` — async, never raises, returns a ``list``
  (``[]`` on failure). ``agency`` is ``"all"`` (default), ``"fda"``,
  ``"ftc"``, ``"cfpb"``, ``"sec"``, ``"epa"``, ``"osha"`` or ``"doj"``;
  ``"all"`` merges all sources, newest first.
* :func:`get_action` — async, never raises, returns a ``dict`` (``{}`` on
  failure). Accepts the prefixed ids returned by :func:`search_enforcement`
  (``fda:<recall_number>`` / ``ftc:<slug>`` / ``cfpb:<complaint_id>`` /
  ``sec:<id>`` / ``epa:<case_number>`` / ``osha:<inspection_number>`` /
  ``doj:<slug>``).
* :func:`watch_company` — async, never raises, returns a ``list`` of
  enforcement/complaint matches for a specific company (compliance
  screening). ``agencies`` is ``"all"`` (default) or a comma-separated
  subset.

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

import asyncio
import html
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_FDA_ENDPOINTS: tuple[str, ...] = (
    "https://api.fda.gov/drug/enforcement.json",
    "https://api.fda.gov/food/enforcement.json",
    "https://api.fda.gov/device/enforcement.json",
)
_FTC_LIST_URL = "https://www.ftc.gov/legal-library/browse/cases-proceedings"
_CFPB_SEARCH_URL = (
    "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
)
_SEC_ADMIN_URL = "https://www.sec.gov/enforcement-litigation/administrative-proceedings"
_SEC_FTS_URL = "https://efts.sec.gov/LATEST/search-index"
_ECHO_CASE_URL = "https://echo.epa.gov/rest/enforcement/case_search"
_OSHA_EST_URL = "https://www.osha.gov/pls/imis/establishmentsearch.html"
_OSHA_DETAIL_URL = "https://www.osha.gov/pls/imis/establishment.html"
_DOJ_API_URL = "https://www.justice.gov/api/v1/press_releases.json"

_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-compliance/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}
_HTML_HEADERS = {
    "User-Agent": _HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml",
}

_MAX_LIMIT = 100
_AGENCIES: tuple[str, ...] = ("fda", "ftc", "cfpb", "sec", "epa", "osha", "doj")
_VALID_AGENCIES = {"all", *_AGENCIES}
# Single-agency queries for the newer enforcement sources fall through the
# chain below so one provider being down never empties the answer.
_AGENCY_FALLBACK: dict[str, tuple[str, ...]] = {
    "epa": ("epa", "osha", "doj"),
    "osha": ("osha", "doj"),
    "doj": ("doj",),
}


# ── Generic helpers ───────────────────────────────────────────────────
def _as_text(value: Any) -> str | None:
    """Coerce a JSON/HTML value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_date(value: str | None) -> str | None:
    """Normalize API dates to ``YYYY-MM-DD`` (or passthrough)."""
    if not value:
        return None
    text = value.strip()
    if len(text) >= 10 and text[4] == "-":
        return text[:10]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text or None


def _mmddyyyy_date(value: str | None) -> str | None:
    """Normalize a ``MM/DD/YYYY`` date (EPA ECHO / OSHA IMIS) to ``YYYY-MM-DD``."""
    if not value:
        return None
    text = value.strip()
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if match:
        month, day, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return text or None


def _strip_tags(raw: str | None) -> str | None:
    """Strip HTML tags/entities from a scraped title fragment."""
    if not raw:
        return None
    text = re.sub(r"<[^>]+>", "", raw)
    text = html.unescape(text).strip()
    return text or None


def _sort_records(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Sort newest-first (missing dates last) and cap at ``limit``."""
    records.sort(key=lambda record: str(record.get("date") or ""), reverse=True)
    return records[:limit]


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop records whose ``id`` was already seen (first occurrence wins)."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for record in records:
        rid = str(record.get("id") or "")
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        result.append(record)
    return result


def _parse_agencies(agencies: str) -> list[str]:
    """Resolve an agencies spec ('all' or comma-separated) to a list."""
    value = str(agencies or "all").strip().lower()
    if not value or value == "all":
        return list(_AGENCIES)
    result: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if part in _AGENCIES and part not in result:
            result.append(part)
    return result


# ── Fetching ──────────────────────────────────────────────────────────
async def _fetch_json(url: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return the parsed JSON object, or ``None`` on failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("enforcement API payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_html(url: str, params: dict[str, str] | None = None) -> str | None:
    """GET ``url`` and return the response text, or ``None`` on failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HTML_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            text = response.text
        if not text:
            raise ValueError("enforcement page payload is empty")
        return text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── FDA (openFDA enforcement) ─────────────────────────────────────────
def _fda_url(endpoint: str, recall_number: str | None) -> str | None:
    """Build a deep-linkable openFDA query URL for one recall number."""
    if not recall_number:
        return None
    query = quote(f'recall_number:"{recall_number}"', safe=":")
    return f"{endpoint}?search={query}"


def _map_fda(raw: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Map an openFDA enforcement object onto the canonical search record."""
    recall_number = _as_text(raw.get("recall_number"))
    firm = _as_text(raw.get("recalling_firm"))
    product = _as_text(raw.get("product_description"))
    title = product or (f"FDA enforcement action - {firm}" if firm else "FDA enforcement action")
    return {
        "agency": "fda",
        "id": f"fda:{recall_number}" if recall_number else None,
        "title": title,
        "type": _as_text(raw.get("classification")) or "FDA Enforcement",
        "company": firm,
        "date": _normalize_date(_as_text(raw.get("recall_initiation_date"))),
        "penalty_amount": None,
        "url": _fda_url(endpoint, recall_number),
        "source": "openfda",
    }


def _fda_detail(raw: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Map an openFDA enforcement object onto the action-detail shape."""
    recall_number = _as_text(raw.get("recall_number"))
    firm = _as_text(raw.get("recalling_firm"))
    classification = _as_text(raw.get("classification"))
    return {
        "agency": "fda",
        "id": f"fda:{recall_number}" if recall_number else None,
        "title": _as_text(raw.get("product_description"))
        or (f"FDA enforcement action - {firm}" if firm else "FDA enforcement action"),
        "summary": _as_text(raw.get("reason_for_recall")),
        "defendants": [firm] if firm else [],
        "penalties": [{"type": classification or "market withdrawal", "amount": None}],
        "url": _fda_url(endpoint, recall_number),
    }


async def _fetch_fda(query: str, limit: int) -> list[dict[str, Any]]:
    async def _one(endpoint: str) -> list[dict[str, Any]]:
        params: dict[str, str] = {"limit": str(limit)}
        if query.strip():
            params["search"] = query.strip()
        payload = await _fetch_json(endpoint, params)
        if payload is None:
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []
        return [_map_fda(raw, endpoint) for raw in results if isinstance(raw, dict)]

    chunks = await asyncio.gather(*(_one(endpoint) for endpoint in _FDA_ENDPOINTS))
    return _sort_records([record for chunk in chunks for record in chunk], limit)


async def _get_fda_action(value: str) -> dict[str, Any]:
    async def _one(endpoint: str) -> dict[str, Any]:
        payload = await _fetch_json(endpoint, {"search": f'recall_number:"{value}"', "limit": "1"})
        if payload is None:
            return {}
        results = payload.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            return _fda_detail(results[0], endpoint)
        return {}

    for record in await asyncio.gather(*(_one(endpoint) for endpoint in _FDA_ENDPOINTS)):
        if record:
            return record
    return {}


# ── FTC (cases & proceedings listing) ─────────────────────────────────
_FTC_ARTICLE_RE = re.compile(
    r'<article about="([^"]+)" class="node node--type-case[^"]*">(.*?)</article>', re.S
)
_FTC_TITLE_RE = re.compile(r'<h[1-6][^>]*class="[^"]*node-title[^"]*"[^>]*>(.*?)</h[1-6]>', re.S)


def _ftc_company_from_title(title: str | None) -> str | None:
    """Best-effort company extraction from an FTC case title."""
    if not title:
        return None
    text = title.strip()
    match = re.match(r"^(.*?), In the Matter of$", text)
    if match:
        return match.group(1).strip()
    match = re.match(r"^FTC v\.\s+(.+?)(?:,\s*(?:et al\.?|and others))?\.?$", text)
    if match:
        return match.group(1).strip()
    return text


def _parse_ftc_listing(page: str) -> list[dict[str, Any]]:
    """Parse the FTC cases & proceedings page into raw case rows."""
    rows: list[dict[str, Any]] = []
    for about, block in _FTC_ARTICLE_RE.findall(page):
        title_match = _FTC_TITLE_RE.search(block)
        title = _strip_tags(title_match.group(1)) if title_match else None
        time_match = re.search(r'<time datetime="([^"]+)"', block)
        docket_match = re.search(
            r'field--name-field-docket-number.*?field__item">([^<]+)<', block, re.S
        )
        type_match = re.search(
            r'field--name-field-case-action-type.*?field__item">([^<]+)<', block, re.S
        )
        slug = about.rstrip("/").rsplit("/", 1)[-1]
        if not title and not slug:
            continue
        rows.append(
            {
                "slug": slug,
                "title": title or slug,
                "date": _normalize_date(_as_text(time_match.group(1) if time_match else None)),
                "docket": _as_text(docket_match.group(1) if docket_match else None),
                "action_type": _as_text(type_match.group(1) if type_match else None),
                "url": f"https://www.ftc.gov{about}" if about.startswith("/") else about,
            }
        )
    return rows


def _map_ftc(raw: dict[str, Any]) -> dict[str, Any]:
    title = _as_text(raw.get("title"))
    return {
        "agency": "ftc",
        "id": f"ftc:{raw.get('slug')}" if raw.get("slug") else None,
        "title": title,
        "type": _as_text(raw.get("action_type")) or "FTC Case",
        "company": _ftc_company_from_title(title),
        "date": _as_text(raw.get("date")),
        "penalty_amount": None,
        "url": _as_text(raw.get("url")),
        "source": "ftc.gov",
    }


def _filter_ftc_rows(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if not needle:
        return rows
    return [
        row
        for row in rows
        if needle
        in " ".join(str(row.get(key) or "") for key in ("title", "docket", "action_type")).lower()
    ]


async def _fetch_ftc(query: str, limit: int) -> list[dict[str, Any]]:
    page = await _fetch_html(_FTC_LIST_URL)
    if page is None:
        return []
    rows = _filter_ftc_rows(_parse_ftc_listing(page), query)
    return _sort_records([_map_ftc(row) for row in rows], limit)


async def _get_ftc_action(value: str) -> dict[str, Any]:
    page = await _fetch_html(f"{_FTC_LIST_URL}/{value}")
    if page is None:
        return {}
    title_match = re.search(r"<title>(.*?)</title>", page, re.S)
    desc_match = re.search(r'<meta name="description" content="([^"]+)"', page, re.S)
    title = _strip_tags(title_match.group(1) if title_match else None)
    summary = _as_text(html.unescape(desc_match.group(1)) if desc_match else None)
    if not title:
        return {}
    return {
        "agency": "ftc",
        "id": f"ftc:{value}",
        "title": title,
        "summary": summary,
        "defendants": [_ftc_company_from_title(title)] if _ftc_company_from_title(title) else [],
        "penalties": [],
        "url": f"{_FTC_LIST_URL}/{value}",
    }


# ── CFPB (consumer complaints API) ────────────────────────────────────
def _map_cfpb(hit: dict[str, Any]) -> dict[str, Any]:
    raw_source = hit.get("_source")
    if isinstance(raw_source, dict):
        source: dict[str, Any] = raw_source
    else:
        source = hit
    complaint_id = _as_text(source.get("complaint_id"))
    product = _as_text(source.get("product"))
    issue = _as_text(source.get("issue"))
    title = " / ".join(part for part in (product, issue) if part) or "Consumer complaint"
    company = _as_text(source.get("company"))
    return {
        "agency": "cfpb",
        "id": f"cfpb:{complaint_id}" if complaint_id else None,
        "title": title,
        "type": product or "CFPB Complaint",
        "company": company,
        "date": _normalize_date(_as_text(source.get("date_received"))),
        "penalty_amount": None,
        "url": (
            f"https://www.consumerfinance.gov/data-research/consumer-complaints/search/"
            f"?q={quote(complaint_id)}"
            if complaint_id
            else None
        ),
        "source": "cfpb",
    }


def _cfpb_detail(hit: dict[str, Any]) -> dict[str, Any]:
    raw_source = hit.get("_source")
    if isinstance(raw_source, dict):
        source: dict[str, Any] = raw_source
    else:
        source = hit
    complaint_id = _as_text(source.get("complaint_id"))
    product = _as_text(source.get("product"))
    issue = _as_text(source.get("issue"))
    title = " / ".join(part for part in (product, issue) if part) or "Consumer complaint"
    company = _as_text(source.get("company"))
    summary = _as_text(source.get("consumer_complaint_narrative")) or _as_text(
        source.get("company_response_to_consumer")
    )
    return {
        "agency": "cfpb",
        "id": f"cfpb:{complaint_id}" if complaint_id else None,
        "title": title,
        "summary": summary,
        "defendants": [company] if company else [],
        "penalties": [],
        "url": (
            f"https://www.consumerfinance.gov/data-research/consumer-complaints/search/"
            f"?q={quote(complaint_id)}"
            if complaint_id
            else None
        ),
    }


async def _cfpb_hits(params: dict[str, str]) -> list[dict[str, Any]]:
    payload = await _fetch_json(_CFPB_SEARCH_URL, params)
    if payload is None:
        return []
    hits = payload.get("hits")
    if not isinstance(hits, dict):
        return []
    items = hits.get("hits")
    if not isinstance(items, list):
        return []
    return [hit for hit in items if isinstance(hit, dict)]


async def _fetch_cfpb(query: str, limit: int) -> list[dict[str, Any]]:
    params: dict[str, str] = {"size": str(limit)}
    if query.strip():
        params["search_term"] = query.strip()
    hits = await _cfpb_hits(params)
    return [_map_cfpb(hit) for hit in hits]


async def _fetch_cfpb_company(company: str, limit: int) -> list[dict[str, Any]]:
    """Company screening: exact ``company`` filter, full-text fallback."""
    params: dict[str, str] = {"size": str(limit), "company": company}
    hits = await _cfpb_hits(params)
    if not hits and company.strip():
        params = {"size": str(limit), "search_term": company.strip()}
        hits = await _cfpb_hits(params)
    return [_map_cfpb(hit) for hit in hits]


async def _get_cfpb_action(value: str) -> dict[str, Any]:
    hits = await _cfpb_hits({"size": "1", "search_term": value})
    for hit in hits:
        raw_source = hit.get("_source")
        if isinstance(raw_source, dict):
            source: dict[str, Any] = raw_source
        else:
            source = hit
        if _as_text(source.get("complaint_id")) == value:
            return _cfpb_detail(hit)
    return {}


# ── SEC (EDGAR full-text + AAER admin proceedings) ────────────────────
def _parse_sec_admin(page: str) -> list[dict[str, Any]]:
    """Parse the SEC administrative-proceedings listing into raw rows."""
    rows: list[dict[str, Any]] = []
    for chunk in page.split('<tr class="pr-list-page-row">')[1:]:
        time_match = re.search(r'<time datetime="([^"]+)"', chunk)
        respondent_match = re.search(
            r"class=['\"]release-view__respondents['\"]><a href=['\"]([^'\"]+)['\"]>([^<]+)</a>",
            chunk,
        )
        release_match = re.search(r'view-table_subfield_value">([^<]+)<', chunk)
        url = _as_text(respondent_match.group(1) if respondent_match else None)
        title = _strip_tags(respondent_match.group(2) if respondent_match else None)
        release_text = _as_text(release_match.group(1) if release_match else None)
        if not title and not release_text:
            continue
        stem = None
        if url:
            stem_match = re.search(r"/([^/]+)\.pdf$", url)
            stem = stem_match.group(1) if stem_match else None
        rows.append(
            {
                "id": stem or release_text,
                "title": title or f"SEC enforcement action ({release_text or 'unknown'})",
                "release": release_text,
                "date": _normalize_date(_as_text(time_match.group(1) if time_match else None)),
                "url": url,
            }
        )
    return rows


def _map_sec_admin(raw: dict[str, Any]) -> dict[str, Any]:
    release = _as_text(raw.get("release")) or ""
    action_type = "AAER" if "AAER" in release.upper() else "Admin Proceeding"
    return {
        "agency": "sec",
        "id": f"sec:{raw.get('id')}" if raw.get("id") else None,
        "title": _as_text(raw.get("title")),
        "type": action_type,
        "company": _as_text(raw.get("title")),
        "date": _as_text(raw.get("date")),
        "penalty_amount": None,
        "url": _as_text(raw.get("url")),
        "source": "sec.gov",
    }


def _map_sec_edgar(hit: dict[str, Any]) -> dict[str, Any]:
    raw_source = hit.get("_source")
    if isinstance(raw_source, dict):
        source: dict[str, Any] = raw_source
    else:
        source = hit
    doc_id = _as_text(hit.get("_id"))
    form = _as_text(source.get("form")) or _as_text(source.get("file_type"))
    date = _normalize_date(_as_text(source.get("file_date"))) or _normalize_date(
        _as_text(source.get("display_date"))
    )
    return {
        "agency": "sec",
        "id": f"sec:{doc_id}" if doc_id else None,
        "title": form or "SEC filing",
        "type": form or "EDGAR Filing",
        "company": None,
        "date": date,
        "penalty_amount": None,
        "url": f"{_SEC_FTS_URL}?q={quote(doc_id)}" if doc_id else None,
        "source": "edgar-fulltext",
    }


def _filter_sec_rows(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if not needle:
        return rows
    return [
        row
        for row in rows
        if needle in " ".join(str(row.get(key) or "") for key in ("title", "release", "id")).lower()
    ]


async def _fetch_sec_admin(query: str, limit: int) -> list[dict[str, Any]]:
    page = await _fetch_html(_SEC_ADMIN_URL)
    if page is None:
        return []
    rows = _filter_sec_rows(_parse_sec_admin(page), query)
    return _sort_records([_map_sec_admin(row) for row in rows], limit)


async def _fetch_sec_edgar(query: str, limit: int) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    payload = await _fetch_json(
        _SEC_FTS_URL,
        {"q": query.strip(), "page": "0", "size": str(limit)},
    )
    if payload is None:
        return []
    hits = payload.get("hits")
    if not isinstance(hits, dict):
        return []
    items = hits.get("hits")
    if not isinstance(items, list):
        return []
    return [_map_sec_edgar(hit) for hit in items if isinstance(hit, dict)]


async def _fetch_sec(query: str, limit: int) -> list[dict[str, Any]]:
    """SEC enforcement: AAER admin listing, plus EDGAR full-text for queries."""
    admin = await _fetch_sec_admin(query, limit)
    if not query.strip():
        return admin
    edgar = await _fetch_sec_edgar(query, limit)
    return _sort_records(_dedupe_records(admin + edgar), limit)


async def _get_sec_action(value: str) -> dict[str, Any]:
    # Prefer EDGAR full-text (handles accession ids and release numbers).
    payload = await _fetch_json(_SEC_FTS_URL, {"q": value, "page": "0", "size": "1"})
    if payload is not None:
        hits = payload.get("hits")
        if isinstance(hits, dict):
            items = hits.get("hits")
            if isinstance(items, list) and items and isinstance(items[0], dict):
                hit = _map_sec_edgar(items[0])
                return {
                    "agency": "sec",
                    "id": hit["id"],
                    "title": hit["title"],
                    "summary": None,
                    "defendants": [],
                    "penalties": [],
                    "url": hit["url"],
                }
    # Fall back to the AAER admin listing (matches release numbers like
    # "34-106135" or "AAER-4595").
    page = await _fetch_html(_SEC_ADMIN_URL)
    if page is None:
        return {}
    for row in _parse_sec_admin(page):
        release = _as_text(row.get("release")) or ""
        if value in release or (row.get("id") and value == row["id"]):
            mapped = _map_sec_admin(row)
            return {
                "agency": "sec",
                "id": mapped["id"],
                "title": mapped["title"],
                "summary": None,
                "defendants": [mapped["company"]] if mapped["company"] else [],
                "penalties": [],
                "url": mapped["url"],
            }
    return {}


# ── EPA (ECHO enforcement case search) ────────────────────────────────
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


# ── OSHA (IMIS establishment inspections) ─────────────────────────────
_OSHA_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_OSHA_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_OSHA_INSPECTION_RE = re.compile(r"\b(\d{7,12}(?:\.\d{3})?)\b")


def _parse_osha_inspections(page: str) -> list[dict[str, Any]]:
    """Signature-parse the OSHA IMIS establishment-search results table.

    Result rows expose inspection number, opening date and establishment
    name (in that order, best-effort). Layout changes degrade to ``[]``.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _OSHA_ROW_RE.findall(page):
        cells = [_strip_tags(cell) or "" for cell in _OSHA_CELL_RE.findall(row)]
        cells = [cell for cell in cells if cell]
        if len(cells) < 3:
            continue
        inspection: str | None = None
        for cell in cells:
            match = _OSHA_INSPECTION_RE.search(cell)
            if match:
                inspection = match.group(1)
                break
        if not inspection or inspection in seen:
            continue
        seen.add(inspection)
        rows.append(
            {
                "id": inspection,
                "title": f"OSHA inspection {inspection}",
                "establishment": cells[-1],
                "date": _mmddyyyy_date(cells[1]) if len(cells) > 1 else None,
                "url": f"{_OSHA_DETAIL_URL}?inspection_number={quote(inspection)}",
            }
        )
    return rows


def _map_osha(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "agency": "osha",
        "id": f"osha:{raw.get('id')}" if raw.get("id") else None,
        "title": _as_text(raw.get("title")),
        "type": "OSHA Inspection",
        "company": _as_text(raw.get("establishment")),
        "date": _as_text(raw.get("date")),
        "penalty_amount": None,
        "url": _as_text(raw.get("url")),
        "source": "osha.gov",
    }


async def _fetch_osha(query: str, limit: int) -> list[dict[str, Any]]:
    """OSHA inspection search (keyless HTML scrape of IMIS, best-effort)."""
    params: dict[str, str] = {"Submit": "Search"}
    if query.strip():
        params["establishment"] = query.strip()
    page = await _fetch_html(_OSHA_EST_URL, params)
    if page is None:
        return []
    try:
        rows = _parse_osha_inspections(page)
    except (re.error, ValueError, TypeError):
        logger.warning("compliance_osha_parse_failed", extra={"query": query})
        return []
    needle = query.strip().lower()
    if needle:
        rows = [
            row
            for row in rows
            if needle in str(row.get("establishment") or "").lower()
            or needle in str(row.get("id") or "").lower()
        ]
    return _sort_records([_map_osha(row) for row in rows], limit)


async def _get_osha_action(value: str) -> dict[str, Any]:
    page = await _fetch_html(_OSHA_DETAIL_URL, {"inspection_number": value})
    if page is None:
        return {}
    title_match = re.search(r"<title>(.*?)</title>", page, re.S)
    title = _strip_tags(title_match.group(1) if title_match else None)
    est_match = re.search(r"Establishment:\s*(?:</?[^>]+>\s*)*([^<]{2,})", page, re.S)
    establishment = _strip_tags(est_match.group(1) if est_match else None)
    if not title and not establishment:
        return {}
    return {
        "agency": "osha",
        "id": f"osha:{value}",
        "title": title or f"OSHA inspection {value}",
        "summary": None,
        "defendants": [establishment] if establishment else [],
        "penalties": [],
        "url": f"{_OSHA_DETAIL_URL}?inspection_number={quote(value)}",
    }


# ── DOJ (press releases / actions API) ────────────────────────────────
def _doj_slug(url: str | None) -> str | None:
    """Last path segment of a DOJ press-release URL (used as a stable id)."""
    if not url:
        return None
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def _map_doj(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a DOJ press-release API result onto the canonical search record."""
    url = _as_text(raw.get("url"))
    return {
        "agency": "doj",
        "id": f"doj:{_doj_slug(url)}" if url else None,
        "title": _as_text(raw.get("title")),
        "type": _as_text(raw.get("type")) or "DOJ Press Release",
        "company": None,
        "date": _normalize_date(_as_text(raw.get("published_at"))),
        "penalty_amount": None,
        "url": url,
        "source": "justice.gov",
    }


async def _fetch_doj(query: str, limit: int) -> list[dict[str, Any]]:
    """DOJ press-release / action search (free JSON API, no key)."""
    params: dict[str, str] = {
        "page": "1",
        "per_page": str(max(1, min(limit, _MAX_LIMIT))),
        "fields": "title,url,published_at,agency,type",
    }
    if query.strip():
        params["query"] = query.strip()
    payload = await _fetch_json(_DOJ_API_URL, params)
    if payload is None:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return _sort_records([_map_doj(raw) for raw in results if isinstance(raw, dict)], limit)


async def _get_doj_action(value: str) -> dict[str, Any]:
    records = await _fetch_doj(value, 1)
    for record in records:
        rid = str(record.get("id") or "")
        if rid == f"doj:{value}" or value in str(record.get("url") or ""):
            return {
                "agency": "doj",
                "id": rid,
                "title": record["title"],
                "summary": None,
                "defendants": [],
                "penalties": [],
                "url": record["url"],
            }
    return {}


# ── Public API ────────────────────────────────────────────────────────
async def search_enforcement(
    agency: str = "all", query: str = "", limit: int = 20
) -> list[dict[str, Any]]:
    """Search enforcement actions across the supported agencies.

    Args:
        agency: ``"all"`` (default, merges every source newest-first),
            ``"fda"``, ``"ftc"``, ``"cfpb"``, ``"sec"``, ``"epa"``,
            ``"osha"``, or ``"doj"``.
        query: Keyword search string (empty = recent actions).
        limit: Max results to return (1-100).

    Returns:
        A list of search records (see module docstring). ``[]`` on failure
        or invalid agency. Never raises.
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
    if normalized == "fda":
        return await _fetch_fda(query, clamped)
    if normalized == "ftc":
        return await _fetch_ftc(query, clamped)
    if normalized == "cfpb":
        return await _fetch_cfpb(query, clamped)
    if normalized == "sec":
        return await _fetch_sec(query, clamped)
    if normalized in _AGENCY_FALLBACK:
        # EPA → OSHA → DOJ fallback chain (see module docstring).
        for source in _AGENCY_FALLBACK[normalized]:
            if source == "epa":
                chain_records = await _fetch_epa(query, clamped)
            elif source == "osha":
                chain_records = await _fetch_osha(query, clamped)
            else:
                chain_records = await _fetch_doj(query, clamped)
            if chain_records:
                return chain_records
        return []
    records: list[dict[str, Any]] = []
    records.extend(await _fetch_fda(query, clamped))
    records.extend(await _fetch_ftc(query, clamped))
    records.extend(await _fetch_cfpb(query, clamped))
    records.extend(await _fetch_sec(query, clamped))
    records.extend(await _fetch_epa(query, clamped))
    records.extend(await _fetch_osha(query, clamped))
    records.extend(await _fetch_doj(query, clamped))
    return _sort_records(_dedupe_records(records), clamped)


async def get_action(agency: str, id: str) -> dict[str, Any]:
    """Fetch one enforcement action by its prefixed id.

    Args:
        agency: ``"fda"``, ``"ftc"``, ``"cfpb"``, ``"sec"``, ``"epa"``,
            ``"osha"``, or ``"doj"``.
        id: The prefixed id returned by :func:`search_enforcement`
            (``fda:<recall_number>`` / ``ftc:<slug>`` /
            ``cfpb:<complaint_id>`` / ``sec:<id>`` /
            ``epa:<case_number>`` / ``osha:<inspection_number>`` /
            ``doj:<slug>``).

    Returns:
        Action detail (see module docstring) or ``{}`` on failure
        (unknown id, network error). Never raises.
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
    if normalized == "fda":
        return await _get_fda_action(rid)
    if normalized == "ftc":
        return await _get_ftc_action(rid)
    if normalized == "cfpb":
        return await _get_cfpb_action(rid)
    if normalized == "sec":
        return await _get_sec_action(rid)
    if normalized == "epa":
        return await _get_epa_action(rid)
    if normalized == "osha":
        return await _get_osha_action(rid)
    return await _get_doj_action(rid)


async def watch_company(company: str, agencies: str = "all") -> list[dict[str, Any]]:
    """Return enforcement/complaint matches for a specific company.

    Args:
        company: Company name to screen (e.g. ``"Acme Foods"``).
        agencies: ``"all"`` (default) or a comma-separated subset
            (``"fda,sec"``).

    Returns:
        A list of search records matching the company, newest first.
        ``[]`` on failure or empty company. Never raises.
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
    for agency in _parse_agencies(agencies):
        if agency == "fda":
            records.extend(await _fetch_fda(name, _MAX_LIMIT))
        elif agency == "ftc":
            records.extend(await _fetch_ftc(name, _MAX_LIMIT))
        elif agency == "cfpb":
            records.extend(await _fetch_cfpb_company(name, _MAX_LIMIT))
        elif agency == "sec":
            records.extend(await _fetch_sec(name, _MAX_LIMIT))
        elif agency == "epa":
            records.extend(await _fetch_epa(name, _MAX_LIMIT))
        elif agency == "osha":
            records.extend(await _fetch_osha(name, _MAX_LIMIT))
        elif agency == "doj":
            records.extend(await _fetch_doj(name, _MAX_LIMIT))
    return _sort_records(_dedupe_records(records), _MAX_LIMIT)


__all__ = ["get_action", "search_enforcement", "watch_company"]
