"""Levels.fyi salary-band data for Pry.

Levels.fyi has no official API. The company/role salary pages
(``https://www.levels.fyi/companies/{company}/salaries/{role}``) are
server-side rendered Next.js pages, so the salary data ships inside the
``__NEXT_DATA__`` JSON blob embedded in the HTML — no JS execution, no
headless browser, free and without auth.

Parsed data
-----------
* ``pageProps.company``  — canonical company name
* ``pageProps.levels``   — job family label
* ``pageProps.averages`` — per-level aggregates: ``base``, ``bonus``,
  ``stock``, ``total`` (median-ish USD) plus ``count`` of samples

Output schema (see ``get_salary``)::

    {
      "company": "Google",
      "role": "Software Engineer",
      "levels": [{"level": "L3", "total_comp": 202529.0, "base_salary": 161233.0, "stock": 31878.0, "bonus": 9418.0}],
      "samples": 103
    }

Contract
--------
* ``get_salary`` is ``async`` and never raises — ``{}`` on any failure.
* If the direct slug 404s, the homepage ``companiesWithLevels`` index is
  consulted for the canonical company name (case-insensitive) and the
  page is retried once.
* A tiny TTL cache avoids hammering Levels.fyi on repeat calls.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(12.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.2,
    max_delay=1.0,
    retryable_exceptions=(httpx.HTTPError, json.JSONDecodeError),
)
_SAFE_EXCEPTIONS: tuple[type[Exception], ...] = (httpx.HTTPError, json.JSONDecodeError, OSError)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_PAGE_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

# role slug -> (title on Levels.fyi, URL slug)
_ROLE_SLUGS: dict[str, tuple[str, str]] = {
    "software_engineer": ("Software Engineer", "software-engineer"),
    "product_manager": ("Product Manager", "product-manager"),
    "data_scientist": ("Data Scientist", "data-scientist"),
    "designer": ("Designer", "designer"),
    "technical_program_manager": ("Technical Program Manager", "technical-program-manager"),
    "hardware_engineer": ("Hardware Engineer", "hardware-engineer"),
    "sales": ("Sales", "sales"),
    "marketing": ("Marketing", "marketing"),
}

# ── In-memory TTL cache ────────────────────────────────────────────────
_CACHE_TTL_SECONDS = 300.0
_salary_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _clear_cache() -> None:
    """Clear the in-memory salary cache (used by tests and maintenance)."""
    _salary_cache.clear()


def _cache_get(key: tuple[str, str]) -> dict[str, Any] | None:
    hit = _salary_cache.get(key)
    if hit is None:
        return None
    inserted, result = hit
    if time.monotonic() - inserted > _CACHE_TTL_SECONDS:
        _salary_cache.pop(key, None)
        return None
    return result


def _cache_set(key: tuple[str, str], result: dict[str, Any]) -> None:
    _salary_cache[key] = (time.monotonic(), result)


# ── Helpers ────────────────────────────────────────────────────────────
def _slugify(value: str) -> str:
    """Levels.fyi company/role slug: lowercase, non-alnum runs -> '-'."""
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _role_names(role: str) -> tuple[str, str]:
    """Map a role string to (Levels.fyi title, URL slug)."""
    key = role.strip().lower().replace(" ", "_")
    if key in _ROLE_SLUGS:
        return _ROLE_SLUGS[key]
    return role.strip(), _slugify(role)


def _num(value: Any) -> float:
    """Coerce a numeric-ish value to float; 0.0 when unparsable."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return float(int(number)) if number.is_integer() else round(number, 2)


# ── HTTP layer ─────────────────────────────────────────────────────────
async def _fetch_text(url: str) -> str | None:
    """GET HTML with timeout and bounded retry; None on failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_PAGE_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except _SAFE_EXCEPTIONS:
        logger.warning("salary_fetch_failed", extra={"url": url})
        return None


def _page_props(html_text: str) -> dict[str, Any] | None:
    """Extract ``pageProps`` from a Levels.fyi Next.js page; None if absent."""
    match = _NEXT_DATA_RE.search(html_text)
    if not match:
        return None
    try:
        data = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return None
    page_props = (data or {}).get("props", {}).get("pageProps", {})
    return page_props if isinstance(page_props, dict) else None


# ── Company-name resolution ────────────────────────────────────────────
async def _resolve_company_name(company: str, role_title: str) -> str | None:
    """Look up the canonical company name from the homepage index."""
    text = await _fetch_text("https://www.levels.fyi/")
    if not text:
        return None
    page_props = _page_props(text)
    if not page_props:
        return None
    companies_with_levels = page_props.get("companiesWithLevels") or {}
    names = (
        companies_with_levels.get(role_title) if isinstance(companies_with_levels, dict) else None
    )
    if not isinstance(names, list):
        return None
    target = company.strip().lower()
    for name in names:
        if isinstance(name, str) and name.lower() == target:
            return name
    for name in names:
        if isinstance(name, str) and target in name.lower():
            return name
    return None


# ── Page fetch + parse ─────────────────────────────────────────────────
async def _fetch_salary_page(company_slug: str, role_slug: str) -> dict[str, Any] | None:
    url = f"https://www.levels.fyi/companies/{company_slug}/salaries/{role_slug}"
    text = await _fetch_text(url)
    if not text:
        return None
    page_props = _page_props(text)
    if (
        not page_props
        or not isinstance(page_props.get("averages"), list)
        or not page_props["averages"]
    ):
        return None
    return page_props


def _parse_salary_page(page_props: dict[str, Any], company: str) -> dict[str, Any]:
    """Turn Levels.fyi pageProps into the salary-band schema."""
    company_obj = page_props.get("company") or {}
    company_name = (
        str(company_obj.get("name") or company) if isinstance(company_obj, dict) else company
    )
    levels_obj = page_props.get("levels") or {}
    role_name = (
        str(levels_obj.get("job_family") or "Software Engineer")
        if isinstance(levels_obj, dict)
        else ""
    )

    levels: list[dict[str, Any]] = []
    samples = 0
    for entry in page_props.get("averages") or []:
        if not isinstance(entry, dict):
            continue
        level = (
            entry.get("primaryLevelName")
            or entry.get("shortestLevelName")
            or entry.get("level")
            or ""
        )
        levels.append(
            {
                "level": str(level),
                "total_comp": _num(entry.get("total")),
                "base_salary": _num(entry.get("base")),
                "stock": _num(entry.get("stock")),
                "bonus": _num(entry.get("bonus")),
            }
        )
        try:
            samples += int(entry.get("count") or 0)
        except (TypeError, ValueError):
            continue

    return {
        "company": company_name,
        "role": role_name,
        "levels": levels,
        "samples": samples,
    }


# ── Public ─────────────────────────────────────────────────────────────
async def get_salary(company: str, role: str = "software_engineer") -> dict[str, Any]:
    """Salary-band data for a company/role from Levels.fyi.

    Returns ``{company, role, levels: [{level, total_comp, base_salary,
    stock, bonus}], samples}``. Never raises — ``{}`` on any failure.
    """
    if not company or not company.strip():
        return {}
    role = role.strip() or "software_engineer"
    cache_key = (company.strip().lower(), role.lower())
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    role_title, role_slug = _role_names(role)
    slug = _slugify(company)
    page_props = await _fetch_salary_page(slug, role_slug)

    if page_props is None:
        canonical = await _resolve_company_name(company, role_title)
        if canonical and _slugify(canonical) != slug:
            page_props = await _fetch_salary_page(_slugify(canonical), role_slug)

    if page_props is None:
        logger.warning("salary_no_data", extra={"company": company, "role": role})
        return {}

    result = _parse_salary_page(page_props, company)
    _cache_set(cache_key, result)
    return result
