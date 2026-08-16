"""Google Play store data — scraped from play.google.com (no API key).

Backed by public store pages:

* Search — ``https://play.google.com/store/search?c=apps`` with the app
  results embedded in ``__NEXT_DATA__`` (and legacy ``AF_initDataCallback``
  blocks). We parse the embedded JSON rather than the DOM.
* Details — ``https://play.google.com/store/apps/details?id={package}``,
  same embedded-JSON approach.
* Reviews — ``https://play.google.com/store/getreviews`` POST, which
  returns JSON prefixed with a ``)]}'`` magic string.

Google does not document these endpoints and may serve a captcha /
anti-bot page to datacenter IPs. When that happens we **flag** it
(setting :data:`last_anti_bot` and logging a warning) and degrade to
``[]`` / ``{}`` — we never raise.

Contract
--------
* :func:`search_apps` — async, never raises, returns a ``list`` (``[]``
  on failure). Keyword search across Play apps (US store, English).
* :func:`get_app_details` — async, never raises, returns a ``dict``
  (``{}`` on failure). Details for a package id.
* :func:`get_reviews` — async, never raises, returns a ``list`` (``[]``
  on failure). Most recent reviews for a package.

Result shapes
-------------
``search_apps`` returns a list of::

    {
        "package": "com.instagram.android", "title": "Instagram",
        "developer": "Instagram", "genre": "Social",
        "rating": 4.0, "rating_count": 16253401, "price": "",
        "url": "https://play.google.com/store/apps/details?id=com.instagram.android",
    }

``get_app_details`` returns the same base fields plus ``summary``,
``description``, ``installs``, ``size``, ``version``, ``updated`` and
``contains_ads``. ``{}`` when the package is unknown.

``get_reviews`` returns a list of::

    {"author": "PlayUser42", "rating": 5, "title": "",
     "body": "Works great", "date": "August 15, 2026", "version": "330.0.0"}

Notes
-----
* ``price`` is empty for free apps; paid apps carry the storefront string
  (e.g. ``"$2.99"``) or a formatted value derived from ``priceValue``.
* Anti-bot detection is best-effort; a captcha page that happens to
  contain app-shaped JSON could be parsed as a stale/cached result.

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
import logging
import re
from typing import TYPE_CHECKING, Any

import httpx

from retry import RetryConfig, async_retry

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://play.google.com/store/search"
_DETAILS_URL = "https://play.google.com/store/apps/details"
_REVIEWS_URL = "https://play.google.com/store/getreviews"
_STORE_URL_TMPL = "https://play.google.com/store/apps/details?id={package}"
_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError, OSError),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
_MAX_LIMIT = 100
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_AF_INIT_RE = re.compile(r"AF_initDataCallback\((\{.*?\})\);?\s*$", re.DOTALL)
_MAGIC_PREFIX = ")]}'"
_ANTI_BOT_MARKERS = (
    "unusual traffic",
    "captcha",
    "recaptcha",
    "enable javascript",
    "are you a robot",
    "verify you're human",
    "verify you are human",
    "access denied",
    "pardon the interruption",
    "sorry, something went wrong",
)

#: Set to True when the last Play request was answered with an anti-bot page.
last_anti_bot: bool = False


# ── Small mappers ─────────────────────────────────────────────────────
def _as_text(value: Any) -> str:
    """Return ``value`` as text, or '' for None."""
    if value is None:
        return ""
    return str(value).strip()


def _as_float(value: Any) -> float | None:
    """Return ``value`` as float, or None when it cannot be parsed."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    """Return ``value`` as int, or None when it cannot be parsed."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _format_price(price: Any, price_value: Any) -> str:
    """Return a storefront price string, or '' for free/unknown."""
    text = _as_text(price)
    if text:
        return text
    value = _as_float(price_value)
    if value is None or value <= 0:
        return ""
    if value == int(value):
        return f"${int(value)}"
    return f"${value:.2f}"


# ── Embedded-JSON walking ─────────────────────────────────────────────
def _iter_dicts(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict in a nested JSON structure (depth-first)."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item)


def _is_app_entry(entry: dict[str, Any]) -> bool:
    """True when ``entry`` looks like a Play app record in embedded JSON."""
    return isinstance(entry.get("appId"), str) and bool(entry.get("title") or entry.get("appName"))


def _find_app_entry(obj: Any, package: str | None = None) -> dict[str, Any] | None:
    """Find the first app-shaped dict in embedded JSON.

    When ``package`` is given, prefer the entry whose ``appId`` matches.
    """
    preferred: dict[str, Any] | None = None
    for entry in _iter_dicts(obj):
        if not _is_app_entry(entry):
            continue
        if package is not None and entry.get("appId") == package:
            return entry
        if preferred is None:
            preferred = entry
    return preferred


def _iter_review_rows(obj: Any) -> Iterator[list[Any]]:
    """Yield rows that look like Play review records in getreviews JSON.

    A getreviews row is a positional list of ~14 slots:
    ``[reviewId, userName, avatar, date, ts, commentary, null, [score],
    [reply], null, null, appVersion, appVersionCode, thumbsUp, ...]``.
    """
    if isinstance(obj, list):
        if (
            len(obj) >= 11
            and isinstance(obj[0], str)
            and isinstance(obj[1], str)
            and isinstance(obj[5], str)
        ):
            yield obj
        for item in obj:
            yield from _iter_review_rows(item)


def _map_app_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Map one embedded-JSON app entry onto the canonical app record."""
    package = _as_text(entry.get("appId"))
    return {
        "package": package,
        "title": _as_text(entry.get("title")) or _as_text(entry.get("appName")),
        "developer": _as_text(entry.get("developer")) or _as_text(entry.get("developerName")),
        "genre": _as_text(entry.get("genre")) or _as_text(entry.get("category")),
        "rating": _as_float(entry.get("appRating")),
        "rating_count": _as_int(entry.get("appRatingCount")) or _as_int(entry.get("appReviews")),
        "price": _format_price(entry.get("price"), entry.get("priceValue")),
        "url": _STORE_URL_TMPL.format(package=package) if package else "",
    }


def _map_details_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Map one details-page app entry onto the canonical details record."""
    base = _map_app_entry(entry)
    return {
        **base,
        "summary": _as_text(entry.get("summary")),
        "description": _as_text(entry.get("appDescription")),
        "installs": _as_text(entry.get("appInstalls")),
        "size": _as_text(entry.get("appSize")),
        "version": _as_text(entry.get("appVersion")),
        "updated": _as_text(entry.get("updated")) or _as_text(entry.get("appUpdated")),
        "contains_ads": bool(entry.get("containsAds", entry.get("appContainsAds"))),
    }


def _map_review_row(row: list[Any]) -> dict[str, Any]:
    """Map one getreviews row onto the canonical review record."""
    score = row[7]
    return {
        "author": _as_text(row[1]),
        "rating": _as_float(score[0]) if isinstance(score, list) and score else None,
        "title": "",
        "body": _as_text(row[5]),
        "date": _as_text(row[3]),
        "version": _as_text(row[11]) if len(row) > 11 else "",
    }


# ── HTTP helpers ──────────────────────────────────────────────────────
def _detect_anti_bot(status_code: int, body: str) -> bool:
    """Return True when the response looks like an anti-bot/captcha page.

    Sets :data:`last_anti_bot` and logs a warning when detected.
    """
    global last_anti_bot
    lowered = (body or "").lower()
    detected = status_code in (403, 429, 503) or any(
        marker in lowered for marker in _ANTI_BOT_MARKERS
    )
    if detected:
        last_anti_bot = True
        logger.warning(
            "google_play_anti_bot_detected",
            extra={
                "status_code": status_code,
                "markers": [m for m in _ANTI_BOT_MARKERS if m in lowered],
            },
        )
    return detected


async def _get_text(url: str, params: dict[str, Any] | None = None) -> str | None:
    """GET ``url`` and return its decoded text, or None on any failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            body = response.text
            if _detect_anti_bot(response.status_code, body):
                raise _AntiBotError(response.status_code)
            response.raise_for_status()
            return body

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None
    except _AntiBotError:
        return None


async def _post_text(url: str, data: dict[str, Any]) -> str | None:
    """POST form data to ``url`` and return decoded text, or None."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.post(url, data=data)
            body = response.text
            if _detect_anti_bot(response.status_code, body):
                raise _AntiBotError(response.status_code)
            response.raise_for_status()
            return body

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None
    except _AntiBotError:
        return None


class _AntiBotError(Exception):
    """Internal marker: the store answered with an anti-bot page."""


def _extract_next_data(html: str) -> Any:
    """Parse the ``__NEXT_DATA__`` JSON blob out of a Play HTML page."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _extract_af_init(html: str) -> list[Any]:
    """Parse legacy ``AF_initDataCallback`` JSON payloads out of a page."""
    payloads: list[Any] = []
    for match in _AF_INIT_RE.finditer(html):
        block = match.group(1)
        # Callback blocks are JS object literals; the useful bit is the
        # ``data: {...}`` value, which we extract with a tolerant brace scan.
        data_start = block.find("data:")
        if data_start == -1:
            continue
        try:
            payloads.append(json.loads(block[data_start + len("data:") :]))
        except json.JSONDecodeError:
            continue
    return payloads


# ── Public API ────────────────────────────────────────────────────────
async def search_apps(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search the US Google Play store for apps matching ``query``.

    Args:
        query: Search terms (e.g. ``"crypto wallet"``).
        limit: Max results (1-100).

    Returns:
        List of app records (see module docstring). ``[]`` on failure
        (blank query, network error, anti-bot page, bad payload).
        Never raises.
    """
    try:
        return await _search_apps(query, limit)
    except Exception:
        logger.exception("google_play_search_crashed", extra={"query": query})
        return []


async def _search_apps(query: str, limit: int) -> list[dict[str, Any]]:
    text = (query or "").strip()
    if not text:
        return []
    limit = max(1, min(int(limit), _MAX_LIMIT))
    html = await _get_text(_SEARCH_URL, params={"q": text, "c": "apps", "hl": "en_US", "gl": "US"})
    if html is None:
        return []
    payload = _extract_next_data(html)
    entries: list[dict[str, Any]] = []
    if payload is not None:
        entries = [e for e in _iter_dicts(payload) if _is_app_entry(e)]
    if not entries:
        for block in _extract_af_init(html):
            entries.extend(e for e in _iter_dicts(block) if _is_app_entry(e))
    apps = [_map_app_entry(e) for e in entries]
    apps = [a for a in apps if a.get("package")][:limit]
    return apps


async def get_app_details(package: str) -> dict[str, Any]:
    """Return details for a single Play app by package id.

    Args:
        package: Android package id (e.g. ``"com.instagram.android"``).

    Returns:
        Details dict (see module docstring), ``{}`` for unknown packages
        or on any failure (including anti-bot). Never raises.
    """
    try:
        return await _get_app_details(package)
    except Exception:
        logger.exception("google_play_details_crashed", extra={"package": package})
        return {}


async def _get_app_details(package: str) -> dict[str, Any]:
    text = (package or "").strip()
    if not text:
        return {}
    html = await _get_text(_DETAILS_URL, params={"id": text, "hl": "en_US", "gl": "US"})
    if html is None:
        return {}
    payload = _extract_next_data(html)
    entry: dict[str, Any] | None = None
    if payload is not None:
        entry = _find_app_entry(payload, package=text)
    if entry is None:
        for block in _extract_af_init(html):
            entry = _find_app_entry(block, package=text)
            if entry is not None:
                break
    if entry is None:
        return {}
    return _map_details_entry(entry)


async def get_reviews(package: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent reviews for a Play app (getreviews POST).

    Args:
        package: Android package id (e.g. ``"com.instagram.android"``).
        limit: Max reviews to return (1-100; Play serves ~40 per page).

    Returns:
        List of review records (see module docstring). ``[]`` on failure
        (unknown package, network error, anti-bot page, bad payload).
        Never raises.
    """
    try:
        return await _get_reviews(package, limit)
    except Exception:
        logger.exception("google_play_reviews_crashed", extra={"package": package})
        return []


async def _get_reviews(package: str, limit: int) -> list[dict[str, Any]]:
    text = (package or "").strip()
    if not text:
        return []
    limit = max(1, min(int(limit), _MAX_LIMIT))
    body = await _post_text(
        _REVIEWS_URL,
        data={
            "authuser": "0",
            "hl": "en_US",
            "gl": "US",
            "id": text,
            "reviewSortOrder": "NEWEST",
            "pageNum": "0",
        },
    )
    if body is None:
        return []
    if body.lstrip().startswith(_MAGIC_PREFIX):
        newline = body.find("\n")
        body = body[newline + 1 :] if newline != -1 else body[len(_MAGIC_PREFIX) :]
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    rows = list(_iter_review_rows(payload))
    reviews = [_map_review_row(r) for r in rows]
    reviews = [r for r in reviews if r.get("author") or r.get("body")]
    return reviews[:limit]
