"""Multi-ATS job board ingestion for Pry — official JSON endpoints.

Aggregates job listings from the six major applicant-tracking systems
that expose free, no-auth, no-anti-bot JSON boards:

- Greenhouse  ``GET https://boards-api.greenhouse.io/v1/boards/{company}/jobs``
- Lever      ``GET https://api.lever.co/v0/postings/{company}?mode=json``
- Ashby      ``GET https://api.ashbyhq.com/posting-api/job-board/{company}``
- Workday    ``POST https://{company}.wd1.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs``
             (JSON body + ``Accept: application/json``; a Workday tenant
             usually requires a browser-like User-Agent and same-origin
             Origin/Referer headers — sent by default, best-effort)
- Workable   ``GET https://apply.workable.com/api/v3/accounts/{company}/jobs``
             (public careers-search feed; no auth, free JSON; list items
             carry title/location/remote + a detail ``url``)
- Breezy HR  ``GET https://{company}.breezy.hr/json``
             (public careers feed; no auth, free JSON; a single response
             holds the whole board, no pagination)
- SmartRecruiters ``GET https://api.smartrecruiters.com/v1/companies/{company}/postings``
             (public postings API; no auth, free JSON; paginated
             ``content`` array, rich per-posting detail endpoint)
- Recruitee ``GET https://{company}.recruitee.com/api/offers``
             (public offers API; no auth, free JSON; per-offer detail
             endpoint carries description/requirements/salary)
- Jobvite  ``GET https://{company}.jobvite.com/api/v1/jobs``
             (public requisitions API; no auth, free JSON; the list items
             embed the full description + apply URL)

Each board's raw shape is normalized into the common listing schema:

    {id, title, company, location, remote, url, posted_at}

and the common detail schema:

    {title, company, location, description, requirements, compensation, url}

Contract
--------
* Every public function is ``async`` and *never raises*: network errors,
  timeouts, HTTP error statuses, bad JSON, and unexpected shapes all
  degrade to ``[]`` / ``{}``.
* ``search_jobs`` runs a keyword match (title + location) across a small
  set of known-good public boards.
* A tiny TTL cache avoids hammering the free boards on repeat calls.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

SUPPORTED_BOARDS: tuple[str, ...] = (
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "workable",
    "breezy",
    "smartrecruiters",
    "recruitee",
    "jobvite",
)

# A few known-good public boards used by ``search_jobs`` (verified live).
SEARCH_COMPANIES: tuple[tuple[str, str], ...] = (
    ("stripe", "greenhouse"),
    ("netlify", "greenhouse"),
    ("leverdemo", "lever"),
    ("linear", "ashby"),
    ("ramp", "ashby"),
    ("replit", "ashby"),
)

# ── HTTP / retry tuning ────────────────────────────────────────────────
_TIMEOUT = httpx.Timeout(10.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.2,
    max_delay=1.0,
    retryable_exceptions=(httpx.HTTPError, json.JSONDecodeError),
)
# BLE001 is enforced: new code must catch specific exception types. This is
# the safe set covering every realistic failure of the HTTP layer.
_SAFE_EXCEPTIONS: tuple[type[Exception], ...] = (httpx.HTTPError, json.JSONDecodeError, OSError)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _BROWSER_UA, "Accept": "application/json"}

# ── In-memory TTL cache ────────────────────────────────────────────────
_CACHE_TTL_SECONDS = 300.0
_list_cache: dict[tuple[str, str, str], tuple[float, list[dict[str, Any]]]] = {}


def _clear_cache() -> None:
    """Clear the in-memory listing cache (used by tests and maintenance)."""
    _list_cache.clear()


def _cache_get(key: tuple[str, str, str]) -> list[dict[str, Any]] | None:
    hit = _list_cache.get(key)
    if hit is None:
        return None
    inserted, items = hit
    if time.monotonic() - inserted > _CACHE_TTL_SECONDS:
        _list_cache.pop(key, None)
        return None
    return items


def _cache_set(key: tuple[str, str, str], items: list[dict[str, Any]]) -> None:
    _list_cache[key] = (time.monotonic(), items)


# ── HTTP layer ─────────────────────────────────────────────────────────
async def _get_json(url: str, *, params: dict[str, str] | None = None) -> Any:
    """GET + JSON-decode with timeout and bounded retry; None on failure."""

    async def _one() -> Any:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except _SAFE_EXCEPTIONS:
        logger.warning("ats_get_failed", extra={"url": url})
        return None


async def _post_json(url: str, *, payload: dict[str, Any]) -> Any:
    """POST + JSON-decode (Workday CXS); None on failure."""

    async def _one() -> Any:
        headers = dict(_HEADERS)
        headers["Content-Type"] = "application/json"
        if "//" in url:
            host = url.split("/")[2]
            headers["Origin"] = f"https://{host}"
            headers["Referer"] = f"https://{host}/"
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except _SAFE_EXCEPTIONS:
        logger.warning("ats_post_failed", extra={"url": url})
        return None


# ── URL builders ───────────────────────────────────────────────────────
def _greenhouse_url(company: str) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"


def _lever_url(company: str) -> str:
    return f"https://api.lever.co/v0/postings/{company}?mode=json"


def _ashby_url(company: str, *, include_compensation: bool = True) -> str:
    suffix = "?includeCompensation=true" if include_compensation else ""
    return f"https://api.ashbyhq.com/posting-api/job-board/{company}{suffix}"


def _workday_url(company: str, site: str) -> str:
    return f"https://{company}.wd1.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs"


def _workable_url(company: str) -> str:
    return f"https://apply.workable.com/api/v3/accounts/{company}/jobs"


def _breezy_url(company: str) -> str:
    return f"https://{company}.breezy.hr/json"


def _smartrecruiters_url(company: str) -> str:
    return f"https://api.smartrecruiters.com/v1/companies/{company}/postings"


def _smartrecruiters_job_url(company: str, job_id: str) -> str:
    return f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}"


def _recruitee_url(company: str) -> str:
    return f"https://{company}.recruitee.com/api/offers"


def _recruitee_job_url(company: str, job_id: str) -> str:
    return f"https://{company}.recruitee.com/api/offers/{job_id}"


def _jobvite_url(company: str) -> str:
    return f"https://{company}.jobvite.com/api/v1/jobs"


def _workday_site(company: str, site: str | None) -> str:
    return site.strip() if site and site.strip() else company


def _workday_payload(limit: int) -> dict[str, Any]:
    return {"appliedFacets": {}, "limit": limit, "offset": 0, "searchText": ""}


# ── Value helpers ──────────────────────────────────────────────────────
def _normalize_dt(value: Any) -> str:
    """Best-effort normalization of a posting date to ISO-8601 UTC.

    Accepts epoch millis (Lever), ISO-8601 strings (Greenhouse, Ashby) and
    opaque strings (Workday); returns the original string when unparsable
    rather than failing.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)) and value > 0:
        try:
            ts = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(ts, tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            return ""
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    except ValueError:
        return text


def _strip_html(text: str) -> str:
    """Strip HTML tags into readable plain text."""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|div|li|ul|ol|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _remote_from_greenhouse(raw: dict[str, Any], location: str) -> bool:
    if raw.get("is_remote") is True:
        return True
    if "remote" in location.lower():
        return True
    for meta in raw.get("metadata") or []:
        if not isinstance(meta, dict):
            continue
        if "remote" not in str(meta.get("name") or "").lower():
            continue
        value = meta.get("value")
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {"remote", "yes", "true"}:
            return True
    return False


def _compensation_from_metadata(metadata: Any) -> str:
    """Pull salary/compensation values out of Greenhouse metadata."""
    out: list[str] = []
    for meta in metadata or []:
        if not isinstance(meta, dict):
            continue
        name = str(meta.get("name") or "")
        if not re.search(r"comp|salary|pay|range", name, re.I):
            continue
        value = meta.get("value")
        if value is None:
            continue
        if isinstance(value, dict):
            unit = str(value.get("unit") or "")
            amount = value.get("amount")
            if amount is not None:
                out.append(f"{name}: {amount} {unit}".strip())
        else:
            out.append(f"{name}: {value}")
    return "; ".join(out)


def _compensation_from_salary_range(salary_range: Any) -> str:
    if not isinstance(salary_range, dict):
        return ""
    min_v = salary_range.get("min")
    max_v = salary_range.get("max")
    if min_v is None and max_v is None:
        return ""
    band = f"{min_v or ''} - {max_v or ''}".strip(" -")
    parts = [band, str(salary_range.get("currency") or ""), str(salary_range.get("interval") or "")]
    return " ".join(p for p in parts if p).strip()


def _compensation_from_ashby(comp: Any) -> str:
    if not isinstance(comp, dict):
        return ""
    for key in ("compensationTierSummary", "scrapeableCompensationSalarySummary"):
        value = comp.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


_REQUIREMENT_TYPES = {
    "requirements",
    "qualifications",
    "minimum_qualifications",
    "what_youll_need",
    "what_you_need",
    "you_have",
    "responsibilities",
}


def _requirements_from_lists(lists: Any) -> str:
    """Lever: extract requirement/qualification sections from ``lists``."""
    if not isinstance(lists, list):
        return ""
    chunks: list[str] = []
    for section in lists:
        if not isinstance(section, dict):
            continue
        text = str(section.get("text") or "").lower()
        if not re.search(r"requirement|qualif|what.*(need|bring|expect)", text):
            continue
        content = section.get("content")
        if isinstance(content, list):
            for item in content:
                cleaned = _strip_html(str(item)) if item else ""
                if cleaned:
                    chunks.append(cleaned)
    return "\n".join(chunks)


def _requirements_from_additional(additional: Any) -> str:
    """Ashby: extract requirement blocks from ``additionalDescriptions``."""
    if not isinstance(additional, list):
        return ""
    chunks: list[str] = []
    for block in additional:
        if not isinstance(block, dict):
            continue
        typ = str(block.get("type") or "").lower()
        value = block.get("value")
        keep = typ in _REQUIREMENT_TYPES or "requirement" in typ or "qualif" in typ
        if keep and isinstance(value, str) and value.strip():
            chunks.append(_strip_html(value))
    return "\n".join(chunks)


# ── Per-board normalizers (list schema) ────────────────────────────────
def _norm_greenhouse(raw: dict[str, Any], company: str) -> dict[str, Any]:
    location = str((raw.get("location") or {}).get("name") or "")
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("title") or ""),
        "company": company,
        "location": location,
        "remote": _remote_from_greenhouse(raw, location),
        "url": str(raw.get("absolute_url") or ""),
        "posted_at": _normalize_dt(raw.get("first_published") or raw.get("updated_at")),
    }


def _norm_lever(raw: dict[str, Any], company: str) -> dict[str, Any]:
    categories = raw.get("categories") or {}
    location = categories.get("location") or ""
    if isinstance(location, list):
        location = ", ".join(str(x) for x in location)
    all_locations = categories.get("allLocations") or []
    if not location and isinstance(all_locations, list) and all_locations:
        location = ", ".join(str(x) for x in all_locations)
    workplace_type = str(raw.get("workplaceType") or "").lower()
    remote = workplace_type == "remote" or "remote" in str(location).lower()
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("text") or ""),
        "company": company,
        "location": str(location),
        "remote": remote,
        "url": str(raw.get("hostedUrl") or ""),
        "posted_at": _normalize_dt(raw.get("createdAt")),
    }


def _norm_ashby(raw: dict[str, Any], company: str) -> dict[str, Any]:
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("title") or ""),
        "company": company,
        "location": str(raw.get("location") or ""),
        "remote": bool(raw.get("remote")),
        "url": str(raw.get("jobUrl") or ""),
        "posted_at": _normalize_dt(raw.get("publishedAt")),
    }


def _norm_workday(raw: dict[str, Any], company: str, site: str) -> dict[str, Any]:
    external_path = str(raw.get("externalPath") or "")
    url = f"https://{company}.wd1.myworkdayjobs.com{external_path}" if external_path else ""
    remote = bool(raw.get("remote")) or bool(raw.get("workdayRemote"))
    return {
        "id": str(raw.get("jobPostingId") or raw.get("externalPath") or ""),
        "title": str(raw.get("title") or ""),
        "company": company,
        "location": str(raw.get("locationsText") or ""),
        "remote": remote,
        "url": url,
        "posted_at": _normalize_dt(raw.get("postedOn")),
    }


def _locations_from_structured(raw: dict[str, Any]) -> str:
    """Best-effort location label from Workable's structured location fields.

    Workable frequently ships ``location`` as null and puts the real value
    in ``locations`` (list of dicts with city/region/country), in a single
    ``location`` dict, or in flat city/state/country keys — rebuild the
    label instead of trusting a null.
    """
    locations = raw.get("locations")
    if isinstance(locations, list) and locations:
        parts: list[str] = []
        for loc in locations:
            if isinstance(loc, dict):
                bits = [
                    str(loc.get("city") or "").strip(),
                    str(loc.get("region") or "").strip(),
                    str(loc.get("country") or "").strip(),
                ]
                bits = [b for b in bits if b]
                if bits:
                    parts.append(", ".join(bits))
            else:
                text = str(loc).strip()
                if text:
                    parts.append(text)
        if parts:
            return "; ".join(parts)
    single = raw.get("location")
    if isinstance(single, dict):
        bits = [
            str(single.get("city") or "").strip(),
            str(single.get("region") or "").strip(),
            str(single.get("country") or "").strip(),
        ]
        bits = [b for b in bits if b]
        if bits:
            return ", ".join(bits)
    flat = [
        str(raw.get(k) or "").strip()
        for k in ("city", "state", "country")
        if str(raw.get(k) or "").strip()
    ]
    if flat:
        return ", ".join(flat)
    return str(single or "").strip()


def _norm_workable(raw: dict[str, Any], company: str) -> dict[str, Any]:
    location = _locations_from_structured(raw)
    workplace = str(raw.get("workplace") or raw.get("workplace_type") or "").lower()
    remote = bool(raw.get("remote")) or workplace in {"remote", "fully_remote", "fully remote"}
    if "remote" in location.lower():
        remote = True
    url = str(raw.get("url") or raw.get("application_url") or raw.get("shortlink") or "")
    if not url:
        shortcode = str(raw.get("shortcode") or "")
        if shortcode:
            url = f"https://apply.workable.com/{company}/j/{shortcode}/"
    return {
        "id": str(raw.get("id") or raw.get("shortcode") or ""),
        "title": str(raw.get("title") or ""),
        "company": company,
        "location": location,
        "remote": remote,
        "url": url,
        "posted_at": _normalize_dt(
            raw.get("published") or raw.get("created_at") or raw.get("published_on")
        ),
    }


def _norm_breezy(raw: dict[str, Any], company: str) -> dict[str, Any]:
    location = ", ".join(
        str(raw.get(key) or "").strip()
        for key in ("location_city", "location_state", "location_country")
        if str(raw.get(key) or "").strip()
    )
    remote = bool(raw.get("is_remote")) or bool(raw.get("remote"))
    url = str(raw.get("apply_url") or raw.get("url") or "")
    if not url:
        posting_id = str(raw.get("posting_id") or "")
        if posting_id:
            url = f"https://{company}.breezy.hr/p/{posting_id}"
    return {
        "id": str(raw.get("posting_id") or raw.get("id") or ""),
        "title": str(raw.get("title") or ""),
        "company": company,
        "location": location,
        "remote": remote,
        "url": url,
        "posted_at": _normalize_dt(
            raw.get("published_date") or raw.get("published_at") or raw.get("created_at")
        ),
    }


def _location_from_sr_location(raw: Any) -> str:
    """Rebuild a location label from SmartRecruiters' structured location."""
    if not isinstance(raw, dict):
        return str(raw or "")
    parts = [
        str(raw.get(key) or "").strip()
        for key in ("city", "region", "country")
        if str(raw.get(key) or "").strip()
    ]
    return ", ".join(parts)


def _norm_smartrecruiters(raw: dict[str, Any], company: str) -> dict[str, Any]:
    location = _location_from_sr_location(raw.get("location"))
    remote = bool((raw.get("location") or {}).get("remote")) or bool(raw.get("remote"))
    if "remote" in location.lower():
        remote = True
    url = str(raw.get("applyUrl") or "")
    if not url:
        posting_id = str(raw.get("id") or "")
        if posting_id:
            url = f"https://jobs.smartrecruiters.com/{company}/{posting_id}"
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("name") or ""),
        "company": company,
        "location": location,
        "remote": remote,
        "url": url,
        "posted_at": _normalize_dt(raw.get("releasedDate")),
    }


def _norm_recruitee(raw: dict[str, Any], company: str) -> dict[str, Any]:
    location = str(raw.get("location") or "")
    if not location:
        bits = [
            str(raw.get(key) or "").strip()
            for key in ("city", "country")
            if str(raw.get(key) or "").strip()
        ]
        location = ", ".join(bits)
    remote = bool(raw.get("remote"))
    if "remote" in location.lower():
        remote = True
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("title") or ""),
        "company": company,
        "location": location,
        "remote": remote,
        "url": str(raw.get("careers_url") or ""),
        "posted_at": _normalize_dt(raw.get("published_at")),
    }


def _norm_jobvite(raw: dict[str, Any], company: str) -> dict[str, Any]:
    location = str(raw.get("location") or "")
    if not location:
        bits = [
            str(raw.get(key) or "").strip()
            for key in ("city", "state", "country")
            if str(raw.get(key) or "").strip()
        ]
        location = ", ".join(bits)
    remote_val = raw.get("remote")
    remote = remote_val is True or (
        isinstance(remote_val, str)
        and remote_val.strip().lower() in {"remote", "yes", "true", "fully remote"}
    )
    if "remote" in location.lower():
        remote = True
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("title") or ""),
        "company": company,
        "location": location,
        "remote": remote,
        "url": str(raw.get("applyUrl") or ""),
        "posted_at": _normalize_dt(raw.get("date")),
    }


# ── Public: list_jobs ──────────────────────────────────────────────────
async def list_jobs(
    company: str, board: str = "greenhouse", limit: int = 50, *, site: str | None = None
) -> list[dict[str, Any]]:
    """List job postings for a company from one ATS board.

    Returns the common listing schema, newest-first as provided by the
    board, truncated to ``limit``. Never raises — ``[]`` on any failure.
    """
    if board not in SUPPORTED_BOARDS or not company or not company.strip():
        return []
    try:
        limit = max(1, min(int(limit or 50), 500))
    except (TypeError, ValueError):
        limit = 50
    company = company.strip()
    cache_key = (board, company, _workday_site(company, site))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached[:limit]

    try:
        if board == "greenhouse":
            data = await _get_json(_greenhouse_url(company))
            raw_jobs = ((data or {}).get("jobs") or []) if isinstance(data, dict) else []
            items = [_norm_greenhouse(j, company) for j in raw_jobs if isinstance(j, dict)]
        elif board == "lever":
            data = await _get_json(_lever_url(company))
            raw_jobs = data if isinstance(data, list) else []
            items = [_norm_lever(j, company) for j in raw_jobs if isinstance(j, dict)]
        elif board == "ashby":
            data = await _get_json(_ashby_url(company))
            raw_jobs = ((data or {}).get("jobs") or []) if isinstance(data, dict) else []
            items = [_norm_ashby(j, company) for j in raw_jobs if isinstance(j, dict)]
        elif board == "workable":
            data = await _get_json(_workable_url(company))
            if isinstance(data, dict):
                raw_jobs = data.get("jobs") or []
            elif isinstance(data, list):
                raw_jobs = data
            else:
                raw_jobs = []
            items = [_norm_workable(j, company) for j in raw_jobs if isinstance(j, dict)]
        elif board == "breezy":
            data = await _get_json(_breezy_url(company))
            if isinstance(data, list):
                raw_jobs = data
            elif isinstance(data, dict):
                raw_jobs = data.get("postings") or data.get("jobs") or []
            else:
                raw_jobs = []
            items = [_norm_breezy(j, company) for j in raw_jobs if isinstance(j, dict)]
        elif board == "smartrecruiters":
            data = await _get_json(_smartrecruiters_url(company))
            raw_jobs = ((data or {}).get("content") or []) if isinstance(data, dict) else []
            items = [_norm_smartrecruiters(j, company) for j in raw_jobs if isinstance(j, dict)]
        elif board == "recruitee":
            data = await _get_json(_recruitee_url(company))
            raw_jobs = ((data or {}).get("offers") or []) if isinstance(data, dict) else []
            items = [_norm_recruitee(j, company) for j in raw_jobs if isinstance(j, dict)]
        elif board == "jobvite":
            data = await _get_json(_jobvite_url(company))
            raw_jobs = ((data or {}).get("requisitions") or []) if isinstance(data, dict) else []
            items = [_norm_jobvite(j, company) for j in raw_jobs if isinstance(j, dict)]
        else:  # workday
            site_name = _workday_site(company, site)
            data = await _post_json(
                _workday_url(company, site_name), payload=_workday_payload(limit)
            )
            raw_jobs = ((data or {}).get("jobPostings") or []) if isinstance(data, dict) else []
            items = [_norm_workday(j, company, site_name) for j in raw_jobs if isinstance(j, dict)]
    except _SAFE_EXCEPTIONS:
        logger.warning("ats_list_failed", extra={"board": board, "company": company})
        return []

    _cache_set(cache_key, items)
    return items[:limit]


# ── Public: search_jobs ────────────────────────────────────────────────
async def search_jobs(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Cross-board keyword search (title + location) over known boards."""
    if not query or not query.strip():
        return []
    try:
        limit = max(1, min(int(limit or 20), 100))
    except (TypeError, ValueError):
        limit = 20
    needle = query.strip().lower()
    results: list[dict[str, Any]] = []
    for company, board in SEARCH_COMPANIES:
        for item in await list_jobs(company, board=board, limit=50):
            hay = f"{item.get('title') or ''} {item.get('location') or ''}".lower()
            if needle in hay:
                results.append(item)
    results.sort(key=lambda item: item.get("posted_at") or "", reverse=True)
    return results[:limit]


# ── Public: get_job ────────────────────────────────────────────────────
async def get_job(
    job_id: str, board: str = "greenhouse", *, company: str | None = None
) -> dict[str, Any]:
    """Fetch one job's full detail (description / requirements / compensation).

    ``company`` is required to build the board URL; returns ``{}`` when it
    is missing or the board responds with an error.
    """
    if not job_id or board not in SUPPORTED_BOARDS:
        return {}
    if not company or not company.strip():
        return {}
    company = company.strip()
    try:
        if board == "greenhouse":
            return await _get_job_greenhouse(company, job_id)
        if board == "smartrecruiters":
            return await _get_job_smartrecruiters(company, job_id)
        if board == "recruitee":
            return await _get_job_recruitee(company, job_id)
        item = await _find_in_board_list(company, board, job_id)
        if item is None:
            return {}
        if board == "lever":
            return _job_detail_from_lever(item, company)
        if board == "ashby":
            return _job_detail_from_ashby(item, company)
        if board == "workable":
            return _job_detail_from_workable(item, company)
        if board == "breezy":
            return _job_detail_from_breezy(item, company)
        if board == "jobvite":
            return _job_detail_from_jobvite(item, company)
        return _job_detail_from_workday(item, company)
    except _SAFE_EXCEPTIONS:
        logger.warning("ats_job_failed", extra={"board": board, "company": company})
        return {}


async def _get_job_greenhouse(company: str, job_id: str) -> dict[str, Any]:
    data = await _get_json(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}")
    if not isinstance(data, dict):
        return {}
    return {
        "title": str(data.get("title") or ""),
        "company": company,
        "location": str((data.get("location") or {}).get("name") or ""),
        "description": _strip_html(str(data.get("content") or "")),
        "requirements": "",
        "compensation": _compensation_from_metadata(data.get("metadata")),
        "url": str(data.get("absolute_url") or ""),
    }


async def _find_in_board_list(company: str, board: str, job_id: str) -> dict[str, Any] | None:
    """Fetch a board's list and locate one posting by id (Lever/Ashby/Workday)."""
    if board == "lever":
        data = await _get_json(_lever_url(company))
        raw = data if isinstance(data, list) else []
        id_key = "id"
    elif board == "ashby":
        data = await _get_json(_ashby_url(company, include_compensation=True))
        raw = ((data or {}).get("jobs") or []) if isinstance(data, dict) else []
        id_key = "id"
    elif board == "workday":
        site_name = _workday_site(company, None)
        data = await _post_json(_workday_url(company, site_name), payload=_workday_payload(20))
        raw = ((data or {}).get("jobPostings") or []) if isinstance(data, dict) else []
        id_key = "jobPostingId"
    elif board == "workable":
        data = await _get_json(_workable_url(company))
        if isinstance(data, dict):
            raw = data.get("jobs") or []
        elif isinstance(data, list):
            raw = data
        else:
            raw = []
        id_key = "id"
    elif board == "breezy":
        data = await _get_json(_breezy_url(company))
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            raw = data.get("postings") or data.get("jobs") or []
        else:
            raw = []
        id_key = "posting_id"
    elif board == "jobvite":
        data = await _get_json(_jobvite_url(company))
        raw = ((data or {}).get("requisitions") or []) if isinstance(data, dict) else []
        id_key = "id"
    else:
        return None
    for item in raw:
        if not isinstance(item, dict):
            continue
        candidate = str(item.get(id_key) or item.get("externalPath") or "")
        if candidate == job_id:
            return item
    return None


def _job_detail_from_lever(item: dict[str, Any], company: str) -> dict[str, Any]:
    categories = item.get("categories") or {}
    location = categories.get("location") or ""
    if isinstance(location, list):
        location = ", ".join(str(x) for x in location)
    description = str(item.get("descriptionPlain") or "")
    if not description:
        description = _strip_html(str(item.get("description") or ""))
    return {
        "title": str(item.get("text") or ""),
        "company": company,
        "location": str(location),
        "description": description,
        "requirements": _requirements_from_lists(item.get("lists")),
        "compensation": _compensation_from_salary_range(item.get("salaryRange")),
        "url": str(item.get("hostedUrl") or ""),
    }


def _job_detail_from_ashby(item: dict[str, Any], company: str) -> dict[str, Any]:
    description = str(item.get("descriptionPlain") or "")
    if not description:
        description = _strip_html(str(item.get("descriptionHtml") or ""))
    return {
        "title": str(item.get("title") or ""),
        "company": company,
        "location": str(item.get("location") or ""),
        "description": description,
        "requirements": _requirements_from_additional(item.get("additionalDescriptions")),
        "compensation": _compensation_from_ashby(item.get("compensation")),
        "url": str(item.get("jobUrl") or ""),
    }


def _job_detail_from_workday(item: dict[str, Any], company: str) -> dict[str, Any]:
    external_path = str(item.get("externalPath") or "")
    url = f"https://{company}.wd1.myworkdayjobs.com{external_path}" if external_path else ""
    # The CXS jobPostings payload carries no description/compensation; the
    # richer job detail endpoint is tenant-specific and not validated.
    return {
        "title": str(item.get("title") or ""),
        "company": company,
        "location": str(item.get("locationsText") or ""),
        "description": "",
        "requirements": "",
        "compensation": "",
        "url": url,
    }


def _job_detail_from_workable(item: dict[str, Any], company: str) -> dict[str, Any]:
    """Workable detail derived from the public list item.

    The careers-search feed's list objects carry description / requirements /
    compensation fields on the full object (the ``?details=true`` widget
    variant); when absent we degrade gracefully to the list-visible fields.
    """
    description = str(item.get("description") or item.get("full_description") or "")
    if not description:
        description = _strip_html(str(item.get("description_html") or ""))
    return {
        "title": str(item.get("title") or ""),
        "company": company,
        "location": _locations_from_structured(item),
        "description": description,
        "requirements": str(item.get("requirements") or ""),
        "compensation": str(item.get("salary") or item.get("compensation") or ""),
        "url": str(item.get("url") or item.get("application_url") or ""),
    }


def _job_detail_from_breezy(item: dict[str, Any], company: str) -> dict[str, Any]:
    """Breezy HR detail derived from the public JSON feed.

    The feed publishes apply-url + salary text but no description body, so
    description/requirements are empty by design (link out for the full ad).
    """
    location = ", ".join(
        str(item.get(key) or "").strip()
        for key in ("location_city", "location_state", "location_country")
        if str(item.get(key) or "").strip()
    )
    return {
        "title": str(item.get("title") or ""),
        "company": company,
        "location": location,
        "description": "",
        "requirements": "",
        "compensation": str(item.get("salary") or ""),
        "url": str(item.get("apply_url") or item.get("url") or ""),
    }


def _compensation_from_sr_comp(comp: Any) -> str:
    """SmartRecruiters ``compensation`` dict -> ``"min - max CURRENCY PERIOD"``."""
    if not isinstance(comp, dict):
        return ""
    min_v = comp.get("min")
    max_v = comp.get("max")
    if min_v is None and max_v is None:
        return ""
    band = f"{min_v or ''} - {max_v or ''}".strip(" -")
    parts = [band, str(comp.get("currency") or ""), str(comp.get("salaryPeriod") or "")]
    return " ".join(p for p in parts if p).strip()


async def _get_job_smartrecruiters(company: str, job_id: str) -> dict[str, Any]:
    """SmartRecruiters posting detail (description / qualifications / comp)."""
    data = await _get_json(_smartrecruiters_job_url(company, job_id))
    if not isinstance(data, dict):
        return {}
    sections = (data.get("jobAd") or {}).get("sections") or {}
    if not isinstance(sections, dict):
        sections = {}
    description = _strip_html(str((sections.get("jobDescription") or {}).get("text") or ""))
    requirements = _strip_html(str((sections.get("qualifications") or {}).get("text") or ""))
    url = str(data.get("applyUrl") or "")
    if not url:
        url = f"https://jobs.smartrecruiters.com/{company}/{job_id}"
    return {
        "title": str(data.get("name") or ""),
        "company": company,
        "location": _location_from_sr_location(data.get("location")),
        "description": description,
        "requirements": requirements,
        "compensation": _compensation_from_sr_comp(data.get("compensation")),
        "url": url,
    }


def _compensation_from_recruitee(offer: dict[str, Any]) -> str:
    """Recruitee offer salary fields -> ``"CURRENCY min - max period"``."""
    min_v = offer.get("salary_min")
    max_v = offer.get("salary_max")
    if min_v is None and max_v is None:
        return ""
    band = f"{min_v or ''} - {max_v or ''}".strip(" -")
    parts = [str(offer.get("salary_currency") or ""), band, str(offer.get("salary_period") or "")]
    return " ".join(p for p in parts if p).strip()


async def _get_job_recruitee(company: str, job_id: str) -> dict[str, Any]:
    """Recruitee offer detail (description / requirements / salary)."""
    data = await _get_json(_recruitee_job_url(company, job_id))
    if not isinstance(data, dict):
        return {}
    offer = data.get("offer")
    if not isinstance(offer, dict) or not offer:
        return {}
    url = str(offer.get("careers_url") or "")
    if not url:
        url = f"https://{company}.recruitee.com/o/{job_id}"
    return {
        "title": str(offer.get("title") or ""),
        "company": company,
        "location": str(offer.get("location") or ""),
        "description": _strip_html(str(offer.get("description") or "")),
        "requirements": _strip_html(str(offer.get("requirements") or "")),
        "compensation": _compensation_from_recruitee(offer),
        "url": url,
    }


def _job_detail_from_jobvite(item: dict[str, Any], company: str) -> dict[str, Any]:
    """Jobvite detail derived from the public list item.

    The requisitions list carries the full (HTML) description and apply URL,
    so no separate detail fetch is needed.
    """
    location = str(item.get("location") or "")
    if not location:
        bits = [
            str(item.get(key) or "").strip()
            for key in ("city", "state", "country")
            if str(item.get(key) or "").strip()
        ]
        location = ", ".join(bits)
    return {
        "title": str(item.get("title") or ""),
        "company": company,
        "location": location,
        "description": _strip_html(str(item.get("jobDescription") or "")),
        "requirements": "",
        "compensation": "",
        "url": str(item.get("applyUrl") or ""),
    }
