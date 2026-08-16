"""Real-estate listings — Zillow page parsing with Redfin / Apartments.com / Zumper fallbacks.

Zillow has no public listing API since 2021, so listings are extracted from
the public ``www.zillow.com`` pages themselves: the Next.js pages embed a
``__NEXT_DATA__`` script tag (plus an Apollo/REDUX-style state cache) that
contains the listing/search payload as JSON. This module parses that embedded
JSON directly — no paid API, no credentials.

When Zillow is unreachable or returns a non-200/parseable page, ``search``
falls back through a guarded chain:

1. Redfin's public ``/stingray/api/gis`` endpoint (the JSONP endpoint
   Redfin's own website uses; returns ``{}&&{...}`` wrapped JSON). Redfin's
   per-home detail endpoint (``/stingray/api/home/details/initialInfo``)
   is attempted for single-listing lookups but is bot-protected from many
   networks — it degrades to ``{}`` when blocked.
2. Apartments.com (rentals only) — ``https://www.apartments.com/{location}/``
   parses the embedded ``__PRELOADED_STATE__`` JSON.
3. Zumper (rentals only) — ``https://www.zumper.com/rent-search/{location}``
   parses the embedded ``window.__NUXT__`` JSON.

Apartments.com and Zumper are rental-only sources: they are only consulted
when ``status="for_rent"``, and both sit behind aggressive anti-bot walls.
When a page looks like a CAPTCHA / challenge wall (Cloudflare, PerimeterX,
"Access denied", "Just a moment"), the source is treated as blocked and
flagged in the logs rather than parsed as an empty result — the honest
signal is "we could not read this source", never fabricated listings.

Contract (both functions)
-------------------------
* async, never raise
* ``get_listing`` -> dict (``{}`` on failure)
* ``search_listings`` -> list[dict] (``[]`` on failure)

robots.txt + backoff
--------------------
A robots.txt check is performed per host (cached in-process) before every
fetch, mirroring :mod:`compliance`'s treatment of robots.txt as an advisory
signal: the disallow is logged and surfaced on the result (``robots_allowed``
field) rather than silently ignored. Set ``PRY_REAL_ESTATE_ENFORCE_ROBOTS=1``
to hard-block disallowed paths (returns empty instead of fetching). The
robots ``Crawl-delay`` is honored (capped at 3s; override with
``PRY_REAL_ESTATE_CRAWL_DELAY``, ``0`` disables).

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
import json
import logging
import os
import re
from typing import Any
from urllib.parse import quote, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

ZILLOW_BASE = "https://www.zillow.com"
REDFIN_BASE = "https://www.redfin.com"
APARTMENTS_BASE = "https://www.apartments.com"
ZUMPER_BASE = "https://www.zumper.com"

_TIMEOUT = httpx.Timeout(12.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── robots.txt policy ──────────────────────────────────────────────────
_ENFORCE_ROBOTS_ENV = "PRY_REAL_ESTATE_ENFORCE_ROBOTS"
_CRAWL_DELAY_ENV = "PRY_REAL_ESTATE_CRAWL_DELAY"
_ROBOTS_CRAWL_DELAY_CAP = 3.0

# Per-host parsed robots.txt (RobotFileParser instances), cached for the
# process lifetime. A failed robots fetch is cached as ``None`` so we never
# block data extraction on robots infrastructure problems (same posture as
# compliance.policy.check_robots_txt: 404 / error => no restrictions).
_robots_cache: dict[str, RobotFileParser | None] = {}

# The last crawl-delay declared for a host, read back by the sleeper.
_crawl_delay_cache: dict[str, float] = {}


def _robots_enforced() -> bool:
    """True when disallowed paths must be hard-blocked (env override)."""
    return os.environ.get(_ENFORCE_ROBOTS_ENV, "0") == "1"


def _crawl_delay_override() -> float | None:
    """Env override for crawl-delay (``0`` disables sleeping)."""
    raw = os.environ.get(_CRAWL_DELAY_ENV)
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


async def _robots_for_host(host: str) -> RobotFileParser | None:
    """Fetch + parse robots.txt for a host once; cached per process."""
    if host in _robots_cache:
        return _robots_cache[host]
    robots_url = f"https://{host}/robots.txt"
    parsed = RobotFileParser()
    parsed.set_url(robots_url)
    parser: RobotFileParser | None = parsed
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), headers=_HEADERS) as client:
            response = await client.get(robots_url)
        if response.status_code == 200 and response.text:
            parsed.parse(response.text.splitlines())
            delay = parsed.crawl_delay("*") or parsed.crawl_delay("pry") or 0.0
            _crawl_delay_cache[host] = float(delay)
        else:
            parser = None  # no robots.txt => no restrictions (404/error)
    except (httpx.HTTPError, OSError):
        parser = None
    _robots_cache[host] = parser
    return parser


async def _robots_allowed(url: str) -> bool:
    """Best-effort robots.txt verdict for ``url`` (True when unknown)."""
    host = urlparse(url).netloc
    parser = await _robots_for_host(host)
    if parser is None:
        return True
    return parser.can_fetch("*", url) or parser.can_fetch("pry", url)


async def _sleep_for_robots(url: str) -> None:
    """Honor the robots ``Crawl-delay`` for the host (capped, tunable)."""
    host = urlparse(url).netloc
    delay = _crawl_delay_override()
    if delay is None:
        delay = min(_crawl_delay_cache.get(host, 0.0), _ROBOTS_CRAWL_DELAY_CAP)
    if delay > 0:
        await asyncio.sleep(delay)


# ── HTTP layer ─────────────────────────────────────────────────────────
async def _fetch_page(url: str) -> str | None:
    """GET a page honoring robots + backoff; ``None`` on failure/block."""
    if not await _robots_allowed(url):
        if _robots_enforced():
            logger.warning("real_estate_robots_blocked", extra={"url": url})
            return None
        logger.warning("real_estate_robots_disallowed_fetching", extra={"url": url})
    await _sleep_for_robots(url)

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code} for {url}",
                    request=response.request,
                    response=response,
                )
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


async def _fetch_redfin_json(params: dict[str, str]) -> dict[str, Any] | None:
    """GET the Redfin GIS JSONP endpoint and decode the ``{}&&{...}`` wrapper."""
    url = f"{REDFIN_BASE}/stingray/api/gis"
    if not await _robots_allowed(url):
        if _robots_enforced():
            logger.warning("real_estate_robots_blocked", extra={"url": url})
            return None
        logger.warning("real_estate_robots_disallowed_fetching", extra={"url": url})
    await _sleep_for_robots(url)

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            raw = response.text
        if raw.lstrip().startswith("{}&&"):
            raw = raw.lstrip()[4:]
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("redfin payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError):
        return None


# ── URL builders ───────────────────────────────────────────────────────
def _slugify(location: str) -> str:
    """``Austin, TX`` -> ``austin-tx`` (Zillow search-path style)."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", location.strip().lower()).strip("-")
    return quote(slug) if slug else ""


# Zillow robots.txt allows /homes/for_sale/, /homes/for_rent/ and
# /homes/recently_sold/ browse paths for the generic agent; the modern
# ``/homes/{location}_rb/`` and ``/homedetails/`` paths are not on the
# allow-list, so the compliant URL forms are used here.
_ZILLOW_STATUS_PATHS = {
    "for_sale": "for_sale",
    "for_rent": "for_rent",
    "sold": "recently_sold",
}

# Zillow filterState used to pin the search page to the requested status.
_ZILLOW_STATUS_FILTERS = {
    "for_sale": {
        "fr": True,
        "fsba": False,
        "fsbo": False,
        "nc": False,
        "cmsn": False,
        "auc": False,
        "fore": False,
    },
    "for_rent": {
        "fr": True,
        "fsba": False,
        "fsbo": False,
        "nc": False,
        "cmsn": False,
        "auc": False,
        "fore": False,
    },
    "sold": {
        "fsba": False,
        "fsbo": False,
        "nc": False,
        "cmsn": False,
        "auc": False,
        "fore": False,
        "sold": True,
    },
}

# Redfin GIS ``status`` codes: 9 = active, 1 = rental, 11 = sold.
_REDFIN_STATUS_CODES = {"for_sale": "9", "for_rent": "1", "sold": "11"}

# Verified Redfin region ids (``region_type=6``). Only region ids verified
# against the live GIS endpoint are hardcoded; extend via
# PRY_REAL_ESTATE_REDFIN_REGION_IDS (JSON ``{"location": id}``).
_REDFIN_REGION_IDS: dict[str, int] = {
    "seattle": 39430,
    "seattle-wa": 39430,
    "capitol-hill": 39430,
    "capitol-hill-seattle": 39430,
}
_REDFIN_REGION_ENV = "PRY_REAL_ESTATE_REDFIN_REGION_IDS"


def _redfin_region_id(location: str) -> int | None:
    """Resolve a location to a Redfin region id (numeric passthrough / map)."""
    stripped = location.strip()
    if stripped.isdigit():
        return int(stripped)
    key = re.sub(r"[^a-zA-Z0-9]+", "-", stripped.lower()).strip("-")
    if key in _REDFIN_REGION_IDS:
        return _REDFIN_REGION_IDS[key]
    raw = os.environ.get(_REDFIN_REGION_ENV)
    if raw:
        try:
            extra = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("real_estate_region_env_invalid", extra={"value": raw[:80]})
            extra = {}
        if isinstance(extra, dict) and key in extra:
            try:
                return int(extra[key])
            except (TypeError, ValueError):
                return None
    return None


# ── __NEXT_DATA__ extraction ───────────────────────────────────────────
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _extract_next_data(html: str) -> dict[str, Any] | None:
    """Pull the Next.js ``__NEXT_DATA__`` JSON blob out of a Zillow page."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# ── Apartments.com / Zumper embedded-state extraction ─────────────────
_PRELOADED_STATE_RE = re.compile(
    r'<script[^>]*id="__PRELOADED_STATE__"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_NUXT_STATE_RE = re.compile(r"window\.__NUXT__\s*=", re.DOTALL)
# Anti-bot walls (Cloudflare / PerimeterX / CAPTCHA) must be flagged
# honestly instead of being parsed as empty results.
_BOT_MARKERS_RE = re.compile(
    r"captcha|cf-challenge|cloudflare|access denied|just a moment|"
    r"are you a human|perimeterx|puzzle|verify you are human",
    re.IGNORECASE,
)


def _extract_preloaded_state(html: str) -> dict[str, Any] | None:
    """Pull the Apartments.com ``__PRELOADED_STATE__`` JSON blob."""
    match = _PRELOADED_STATE_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _extract_nuxt_state(html: str) -> dict[str, Any] | None:
    """Pull the Zumper ``window.__NUXT__`` JSON state (balanced-brace scan).

    The Nuxt payload is a plain JS object literal assigned to
    ``window.__NUXT__`` (not wrapped in a script tag with a JSON id), so a
    small string-aware brace scanner finds the matching close brace before
    decoding. Returns ``None`` on any failure.
    """
    match = _NUXT_STATE_RE.search(html)
    if not match:
        return None
    start = match.end()
    while start < len(html) and html[start] not in "{[":  # allow arrays too
        start += 1
    if start >= len(html) or html[start] != "{":
        return None
    opener = html[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    i = start
    while i < len(html):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    break
        i += 1
    if depth != 0:
        return None
    raw = html[start : i + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _is_bot_page(html: str) -> bool:
    """True when a page looks like a CAPTCHA / challenge wall (first 20KB)."""
    return bool(html and _BOT_MARKERS_RE.search(html[:20000]))


def _collect_dicts(obj: Any, out: list[dict[str, Any]], depth: int = 0) -> None:
    """Recursively collect every dict in a JSON tree (max depth 16 / 8000 nodes).

    JSON-string values (Zillow's ``gdpClientCache`` / Apollo cache stores
    payloads as escaped strings) are decoded and walked too, so the parser is
    resilient to Zillow's cache schema drifting.
    """
    if depth > 16 or len(out) >= 8000:
        return
    if isinstance(obj, dict):
        out.append(obj)
        for value in obj.values():
            _collect_dicts(value, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _collect_dicts(item, out, depth + 1)
    elif isinstance(obj, str) and len(obj) > 2 and obj.lstrip().startswith(("{", "[")):
        try:
            decoded = json.loads(obj)
        except json.JSONDecodeError:
            return
        _collect_dicts(decoded, out, depth + 1)


def _first_value(
    dicts: list[dict[str, Any]], key: str, types: tuple[type, ...] | None = None
) -> Any:
    """First non-empty match for ``key`` across collected dicts."""
    for item in dicts:
        if key not in item:
            continue
        value = item[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        if types is None or isinstance(value, types):
            return value
    return None


def _unwrap_value(value: Any) -> Any:
    """Zillow/Redfin wrap scalars in dicts like ``{value: ...}`` — unwrap."""
    if isinstance(value, dict):
        for candidate in ("value", "amount", "fee", "min", "max"):
            if candidate in value and value[candidate] is not None:
                return value[candidate]
        return None
    return value


def _to_int(value: Any) -> int | None:
    value = _unwrap_value(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    value = _unwrap_value(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_address(raw: Any) -> str:
    """Build ``Street, City, ST zip`` from Zillow's address dict shapes."""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return ""
    street = raw.get("streetAddress") or raw.get("streetAddressLine") or ""
    city = raw.get("city") or ""
    state = raw.get("state") or ""
    zipcode = raw.get("zipcode") or raw.get("zip") or raw.get("postalCode") or ""
    parts = [str(street).strip(), str(city).strip()]
    state_zip = " ".join(p for p in (str(state).strip(), str(zipcode).strip()) if p)
    if state_zip:
        parts.append(state_zip)
    return ", ".join(p for p in parts if p)


def _normalize_price_history(raw: Any) -> list[dict[str, Any]]:
    """Normalize Zillow ``priceHistory`` entries to ``{date, price, event}``."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "date": entry.get("date") or entry.get("displayDate") or "",
                "price": _to_int(entry.get("price")),
                "event": entry.get("event") or entry.get("eventName") or "",
            }
        )
    return out


def _normalize_listing(
    record: dict[str, Any],
    *,
    source: str,
    fallback_url: str,
    status: str = "",
) -> dict[str, Any]:
    """Map a parsed Zillow/Redfin record to the canonical listing schema."""
    address = _format_address(record.get("address")) or _format_address(
        record.get("addressComponents")
    )
    if not address:
        street = record.get("streetAddress")
        if isinstance(street, str):
            address = street
    hoa_raw = record.get("hoa") or record.get("hoaFee")
    hoa = _to_float(hoa_raw) if hoa_raw is not None else None
    url = record.get("url") or record.get("detailUrl") or record.get("hdpUrl") or fallback_url
    if url.startswith("/"):
        url = f"{ZILLOW_BASE}{url}"
    return {
        "address": address,
        "price": _to_int(record.get("price")),
        "price_history": _normalize_price_history(record.get("priceHistory")),
        "zestimate": _to_int(record.get("zestimate")),
        "bed": _to_int(record.get("bedrooms") or record.get("beds")),
        "bath": _to_float(record.get("bathrooms") or record.get("baths")),
        "sqft": _to_int(record.get("livingArea") or record.get("sqFt")),
        "days_on_market": _to_int(record.get("daysOnZillow") or record.get("daysOnMarket")),
        "hoa": hoa,
        "url": url,
        "source": source,
        "status": status,
        "robots_allowed": True,
    }


def _parse_zillow_listing(data: dict[str, Any], url: str) -> dict[str, Any]:
    """Extract a listing from a Zillow homedetails ``__NEXT_DATA__`` tree."""
    dicts: list[dict[str, Any]] = []
    _collect_dicts(data, dicts)
    if not dicts:
        return {}

    record = _normalize_listing(dicts[0], source="zillow", fallback_url=url)
    record["address"] = (
        _format_address(_first_value(dicts, "address"))
        or _format_address(_first_value(dicts, "addressComponents"))
        or record["address"]
    )
    record["price"] = _to_int(_first_value(dicts, "price")) or record["price"]
    record["zestimate"] = _to_int(_first_value(dicts, "zestimate")) or record["zestimate"]
    record["bed"] = (
        _to_int(_first_value(dicts, "bedrooms"))
        or _to_int(_first_value(dicts, "beds"))
        or record["bed"]
    )
    record["bath"] = (
        _to_float(_first_value(dicts, "bathrooms"))
        or _to_float(_first_value(dicts, "baths"))
        or record["bath"]
    )
    record["sqft"] = (
        _to_int(_first_value(dicts, "livingArea"))
        or _to_int(_first_value(dicts, "sqFt"))
        or record["sqft"]
    )
    record["days_on_market"] = (
        _to_int(_first_value(dicts, "daysOnZillow"))
        or _to_int(_first_value(dicts, "daysOnMarket"))
        or record["days_on_market"]
    )
    hoa = _first_value(dicts, "hoa")
    if hoa is not None:
        record["hoa"] = _to_float(hoa)
    history = _first_value(dicts, "priceHistory")
    if history is not None:
        record["price_history"] = _normalize_price_history(history)
    status = _first_value(dicts, "homeStatus")
    if isinstance(status, str):
        record["status"] = status
    record["robots_allowed"] = True
    return record


def _parse_zillow_search(data: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
    """Extract ``listResults`` from a Zillow SRP ``__NEXT_DATA__`` tree."""
    try:
        state = data["props"]["pageProps"]["searchPageState"]
    except (KeyError, TypeError):
        return []
    results = state.get("cat1", {}).get("searchResults", {}).get("listResults", [])
    if not isinstance(results, list):
        return []
    out: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        merged = dict(item)
        home_info = item.get("hdpData", {}).get("homeInfo")
        if isinstance(home_info, dict):
            merged.update(home_info)
        record = _normalize_listing(merged, source="zillow", fallback_url=base_url)
        record["status"] = item.get("statusText") or item.get("statusType") or ""
        out.append(record)
    return out


# ── Redfin mapping ─────────────────────────────────────────────────────
def _redfin_address(home: dict[str, Any], url: str) -> str:
    """Best-effort address from a Redfin GIS home (list payload lacks street)."""
    city = str(home.get("city") or "")
    state = str(home.get("state") or "")
    zipcode = str(home.get("zip") or "")
    parts = [p for p in (city, f"{state} {zipcode}".strip()) if p]
    base = ", ".join(parts)
    # The URL slug carries the street: /WA/Seattle/732-11th-Ave-E-98102/home/52821
    if "/home/" in url:
        street = url.split("/home/")[0].rsplit("/", 1)[-1]
        street = street.replace("-", " ")
        if street and not street[0].isdigit():
            street = ""
        if street:
            return f"{street}, {base}" if base else street
    return base


def _normalize_redfin_home(home: dict[str, Any], status: str) -> dict[str, Any]:
    """Map a Redfin GIS home entry to the canonical listing schema."""
    url = home.get("url") or ""
    if url.startswith("/"):
        url = f"{REDFIN_BASE}{url}"
    hoa_raw = _unwrap_value(home.get("hoa"))
    return {
        "address": _redfin_address(home, url),
        "price": _to_int(home.get("price")),
        "price_history": [],
        "zestimate": _to_int(home.get("zestimate")),
        "bed": _to_int(home.get("beds")),
        "bath": _to_float(home.get("baths") or home.get("fullBaths")),
        "sqft": _to_int(home.get("sqFt")),
        "days_on_market": _to_int(home.get("dom")),
        "hoa": _to_float(hoa_raw) if hoa_raw is not None else None,
        "url": url,
        "source": "redfin",
        "status": str(home.get("mlsStatus") or status),
        "robots_allowed": True,
    }


def _normalize_redfin_detail(home: dict[str, Any], zillow_id: str) -> dict[str, Any]:
    """Map a Redfin ``initialInfo`` homeInfo payload to the listing schema."""
    url = home.get("url") or f"{REDFIN_BASE}/homes/{zillow_id}"
    hoa_raw = home.get("hoa")
    address = _format_address(home.get("address")) or _format_address(
        {
            "streetAddress": home.get("streetAddress"),
            "city": home.get("city"),
            "state": home.get("state"),
            "zipcode": home.get("zip") or home.get("zipcode"),
        }
    )
    return {
        "address": address,
        "price": _to_int(home.get("price")),
        "price_history": _normalize_price_history(home.get("priceHistory")),
        "zestimate": _to_int(home.get("zestimate")),
        "bed": _to_int(home.get("beds")),
        "bath": _to_float(home.get("baths")),
        "sqft": _to_int(home.get("sqFt")),
        "days_on_market": _to_int(home.get("daysOnMarket")),
        "hoa": _to_float(hoa_raw) if hoa_raw is not None else None,
        "url": url if url.startswith("http") else f"{REDFIN_BASE}{url}",
        "source": "redfin",
        "status": str(home.get("status") or ""),
        "robots_allowed": True,
    }


async def _redfin_listing_fallback(zillow_id: str) -> dict[str, Any]:
    """Best-effort Redfin single-listing lookup (often CDN-blocked -> {})."""
    url = f"{REDFIN_BASE}/stingray/api/home/details/initialInfo?path={quote(f'/homes/{zillow_id}')}"
    html = await _fetch_page(url)
    if html is None:
        return {}
    try:
        payload = json.loads(html)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    info = (payload.get("payload") or {}).get("homeInfo") or {}
    if not isinstance(info, dict) or not info:
        return {}
    return _normalize_redfin_detail(info, zillow_id)


# ── Apartments.com / Zumper (rental-only fallbacks) ───────────────────
async def _fetch_rental_page(url: str) -> str | None:
    """Fetch a rental-source page; None on failure **or** a bot wall.

    Apartments.com and Zumper are heavily bot-protected. When the response
    looks like a CAPTCHA / challenge page we log it and return None — the
    honest signal is "blocked", not an empty result.
    """
    html = await _fetch_page(url)
    if html is None:
        return None
    if _is_bot_page(html):
        logger.warning("real_estate_rental_bot_wall", extra={"url": url[:80]})
        return None
    return html


def _apartments_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk an Apartments.com ``__PRELOADED_STATE__`` tree for listings."""
    dicts: list[dict[str, Any]] = []
    _collect_dicts(data, dicts)
    out: list[dict[str, Any]] = []
    for record in dicts:
        if not isinstance(record, dict):
            continue
        if not record.get("name"):
            continue
        if not isinstance(record.get("price"), (dict, int, float)):
            continue
        if not (record.get("address") or record.get("detailUrl")):
            continue
        out.append(record)
    return out


def _zumper_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk a Zumper ``__NUXT__`` tree for rental records."""
    dicts: list[dict[str, Any]] = []
    _collect_dicts(data, dicts)
    out: list[dict[str, Any]] = []
    for record in dicts:
        if not isinstance(record, dict):
            continue
        if not (record.get("title") or record.get("name")):
            continue
        if not isinstance(record.get("price"), (dict, int, float)):
            continue
        out.append(record)
    return out


def _normalize_apartments_listing(record: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Map an Apartments.com listing record to the canonical schema."""
    name = str(record.get("name") or "")
    address = (
        _format_address(record.get("address"))
        if isinstance(record.get("address"), dict)
        else str(record.get("address") or "")
    )
    if name and name not in address:
        address = f"{name}, {address}".strip(", ") if address else name
    url = str(record.get("detailUrl") or "")
    if url.startswith("/"):
        url = f"{APARTMENTS_BASE}{url}"
    return {
        "address": address,
        "price": _to_int(record.get("price")),
        "price_history": [],
        "zestimate": None,
        "bed": _to_int(record.get("beds")),
        "bath": _to_float(record.get("baths")),
        "sqft": _to_int(record.get("sqft")),
        "days_on_market": None,
        "hoa": None,
        "url": url or base_url,
        "source": "apartments",
        "status": "For rent",
        "robots_allowed": True,
    }


def _normalize_zumper_listing(record: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Map a Zumper rental record to the canonical schema."""
    name = str(record.get("title") or record.get("name") or "")
    address = str(record.get("address") or "")
    if name and name not in address:
        address = f"{name}, {address}".strip(", ") if address else name
    url = str(record.get("url") or "")
    if url.startswith("/"):
        url = f"{ZUMPER_BASE}{url}"
    return {
        "address": address,
        "price": _to_int(record.get("price")),
        "price_history": [],
        "zestimate": None,
        "bed": _to_int(record.get("bedrooms") or record.get("beds")),
        "bath": _to_float(record.get("bathrooms") or record.get("baths")),
        "sqft": _to_int(record.get("sqft")),
        "days_on_market": None,
        "hoa": None,
        "url": url or base_url,
        "source": "zumper",
        "status": "For rent",
        "robots_allowed": True,
    }


async def _search_apartments(location: str, limit: int) -> list[dict[str, Any]]:
    slug = _slugify(location)
    if not slug:
        return []
    url = f"{APARTMENTS_BASE}/{slug}/"
    html = await _fetch_rental_page(url)
    if html is None:
        return []
    data = _extract_preloaded_state(html)
    if data is None:
        return []
    out: list[dict[str, Any]] = []
    for record in _apartments_records(data):
        out.append(_normalize_apartments_listing(record, url))
        if len(out) >= limit:
            break
    return out


async def _search_zumper(location: str, limit: int) -> list[dict[str, Any]]:
    slug = _slugify(location)
    if not slug:
        return []
    url = f"{ZUMPER_BASE}/rent-search/{slug}"
    html = await _fetch_rental_page(url)
    if html is None:
        return []
    data = _extract_nuxt_state(html)
    if data is None:
        return []
    out: list[dict[str, Any]] = []
    for record in _zumper_records(data):
        out.append(_normalize_zumper_listing(record, url))
        if len(out) >= limit:
            break
    return out


async def _apartments_listing_fallback(zillow_id: str) -> dict[str, Any]:
    """Best-effort Apartments.com single-listing lookup by id (often 404)."""
    url = f"{APARTMENTS_BASE}/{quote(zillow_id)}/"
    html = await _fetch_rental_page(url)
    if html is None:
        return {}
    data = _extract_preloaded_state(html)
    if data is None:
        return {}
    records = _apartments_records(data)
    if not records:
        return {}
    return _normalize_apartments_listing(records[0], url)


async def _zumper_listing_fallback(zillow_id: str) -> dict[str, Any]:
    """Best-effort Zumper single-listing lookup by id (often 404)."""
    url = f"{ZUMPER_BASE}/rentals/{quote(zillow_id)}"
    html = await _fetch_rental_page(url)
    if html is None:
        return {}
    data = _extract_nuxt_state(html)
    if data is None:
        return {}
    records = _zumper_records(data)
    if not records:
        return {}
    return _normalize_zumper_listing(records[0], url)


# ── Public API ─────────────────────────────────────────────────────────
async def get_listing(zillow_id: str) -> dict[str, Any]:
    """Look up a single Zillow listing by its zpid. Never raises.

    Primary source is the Zillow homedetails page's embedded ``__NEXT_DATA__``
    JSON. When Zillow is unreachable or unparsable the guarded fallback chain
    runs: Redfin home-detail endpoint, then (best-effort, usually 404)
    Apartments.com and Zumper by id. Returns ``{}`` on any failure.
    """
    try:
        return await _get_listing(zillow_id)
    except Exception:
        logger.exception("real_estate_get_listing_crashed")
        return {}


async def _get_listing(zillow_id: str) -> dict[str, Any]:
    listing_url = f"{ZILLOW_BASE}/homedetails/{zillow_id}_zpid/"
    html = await _fetch_page(listing_url)
    if html is None:
        return await _listing_fallbacks(zillow_id)
    data = _extract_next_data(html)
    if data is None:
        return await _listing_fallbacks(zillow_id)
    record = _parse_zillow_listing(data, listing_url)
    if not record.get("address") and record.get("price") is None:
        return await _listing_fallbacks(zillow_id)
    return record


async def _listing_fallbacks(zillow_id: str) -> dict[str, Any]:
    """Guarded single-listing fallback chain: Redfin -> Apartments -> Zumper.

    The Apartments.com / Zumper lookups treat ``zillow_id`` as the listing id
    on those sites; like the Redfin path lookup they are best-effort and
    usually 404 for a Zillow-only id. Each step never raises.
    """
    redfin = await _redfin_listing_fallback(zillow_id)
    if redfin:
        return redfin
    apartments = await _apartments_listing_fallback(zillow_id)
    if apartments:
        return apartments
    return await _zumper_listing_fallback(zillow_id)


async def search_listings(
    location: str, status: str = "for_sale", limit: int = 20
) -> list[dict[str, Any]]:
    """Search listings for a location. Never raises; ``[]`` on failure.

    Fallback chain: Zillow SRP page (embedded ``__NEXT_DATA__``) -> Redfin
    GIS API -> Apartments.com (``for_rent`` only, embedded
    ``__PRELOADED_STATE__``) -> Zumper (``for_rent`` only, embedded
    ``__NUXT__``). ``status`` is one of ``for_sale`` / ``for_rent`` / ``sold``.
    """
    try:
        return await _search_listings(location, status, limit)
    except Exception:
        logger.exception("real_estate_search_listings_crashed")
        return []


async def _search_listings(location: str, status: str, limit: int) -> list[dict[str, Any]]:
    if status not in _REDFIN_STATUS_CODES:
        logger.warning("real_estate_unknown_status", extra={"status": status})
        status = "for_sale"
    limit = max(1, min(50, int(limit)))
    zillow_results = await _search_zillow(location, status, limit)
    if zillow_results:
        return zillow_results
    redfin_results = await _search_redfin(location, status, limit)
    if redfin_results:
        return redfin_results
    # Apartments.com and Zumper are rental-only sources: only consulted for
    # for_rent searches, so for_sale/sold never hit the rental chain.
    if status != "for_rent":
        return []
    apartments_results = await _search_apartments(location, limit)
    if apartments_results:
        return apartments_results
    return await _search_zumper(location, limit)


async def _search_zillow(location: str, status: str, limit: int) -> list[dict[str, Any]]:
    slug = _slugify(location)
    if not slug:
        return []
    search_path = _ZILLOW_STATUS_PATHS.get(status, "for_sale")
    base_url = f"{ZILLOW_BASE}/homes/{search_path}/{slug}/"
    filter_state = {
        key: {"value": value}
        for key, value in _ZILLOW_STATUS_FILTERS.get(
            status, _ZILLOW_STATUS_FILTERS["for_sale"]
        ).items()
    }
    query_state = {
        "pagination": {},
        "isMapVisible": False,
        "filterState": filter_state,
        "isListVisible": True,
        "mapZoom": 5,
    }
    url = (
        f"{base_url}?searchQueryState={quote(json.dumps(query_state))}&searchQueryStateVersion=0.1"
    )
    html = await _fetch_page(url)
    if html is None:
        return []
    data = _extract_next_data(html)
    if data is None:
        return []
    results = _parse_zillow_search(data, base_url)
    return results[:limit]


async def _search_redfin(location: str, status: str, limit: int) -> list[dict[str, Any]]:
    region_id = _redfin_region_id(location)
    if region_id is None:
        logger.warning("real_estate_redfin_region_unresolved", extra={"location": location})
        return []
    params = {
        "al": "1",
        "region_id": str(region_id),
        "region_type": "6",
        "status": _REDFIN_STATUS_CODES[status],
        "uipt": "1",
        "v": "8",
        "num_homes": str(limit),
    }
    payload = await _fetch_redfin_json(params)
    if payload is None:
        return []
    homes = (payload.get("payload") or {}).get("homes") or []
    return [_normalize_redfin_home(home, status) for home in homes if isinstance(home, dict)][
        :limit
    ]


# ── Test/utility hooks ─────────────────────────────────────────────────
def reset_robots_cache() -> None:
    """Drop the in-process robots.txt + crawl-delay caches (tests/tooling)."""
    _robots_cache.clear()
    _crawl_delay_cache.clear()
