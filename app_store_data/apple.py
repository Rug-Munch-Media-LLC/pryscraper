"""Apple App Store data — free, no auth, no API key.

Backed by Apple's public iTunes endpoints:

* Search API — ``https://itunes.apple.com/search`` (``entity=software``)
  for app keyword search. Free, no key.
* Lookup API — ``https://itunes.apple.com/lookup`` for single-app details
  by numeric App Store id.
* Customer reviews RSS — ``https://itunes.apple.com/us/rss/\
customerreviews/id={id}/sortBy=mostRecent/json`` for the most recent
reviews of an app. Free, no key.

Contract
--------
* :func:`search_apps` — async, never raises, returns a ``list`` (``[]``
  on failure). Keyword search across US App Store software.
* :func:`get_app_details` — async, never raises, returns a ``dict``
  (``{}`` on failure). Details for a single app id.
* :func:`get_reviews` — async, never raises, returns a ``list`` (``[]``
  on failure). Most recent customer reviews.

Result shapes
-------------
``search_apps`` returns a list of::

    {
        "app_id": 284882215, "title": "Facebook", "developer": "Meta",
        "genre": "Social Networking", "rating": 4.3, "rating_count": 20568113,
        "price": "Free", "version": "472.0", "url": "https://apps.apple.com/us/app/...",
    }

``get_app_details`` returns the same base fields plus ``description``,
``seller_name``, ``release_date``, ``min_os``, ``size_bytes``,
``screenshots`` and ``currency``. ``{}`` when the id is unknown.

``get_reviews`` returns a list of::

    {"author": "AppUser99", "rating": 5, "title": "Love it",
     "body": "The best app", "date": "2026-08-15T12:00:00-07:00",
     "version": "472.0"}

Free-API terms: the iTunes Search/Lookup/RSS endpoints have no documented
hard rate limit; be polite (one request per search, small ``limit``).
Backoff: 2 retries, exponential (0.4s -> 1.6s), same as climate_data.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://itunes.apple.com/search"
_LOOKUP_URL = "https://itunes.apple.com/lookup"
_REVIEWS_URL_TMPL = (
    "https://itunes.apple.com/us/rss/customerreviews/id/{app_id}/sortBy=mostRecent/json"
)
_COUNTRY = "us"
_TIMEOUT = httpx.Timeout(15.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError, OSError),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-appstore/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json, text/plain, */*",
}
_MAX_LIMIT = 200


# ── Small mappers ─────────────────────────────────────────────────────
def _as_text(value: Any) -> str:
    """Return ``value`` as text, handling ``{"label": ...}`` payloads."""
    if isinstance(value, dict):
        return _as_text(value.get("label"))
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


def _as_url(value: Any) -> str:
    """Return a track URL, or ``apps.apple.com`` fallback derived from id."""
    text = _as_text(value)
    if text:
        return text
    return ""


# ── HTTP helpers ──────────────────────────────────────────────────────
async def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    """GET ``url`` and return its decoded JSON (any shape), or None."""

    async def _one() -> Any:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


def _map_app(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one iTunes result object onto the canonical app record."""
    app_id = _as_int(raw.get("trackId"))
    return {
        "app_id": app_id,
        "title": _as_text(raw.get("trackName")),
        "developer": _as_text(raw.get("artistName")),
        "genre": _as_text(raw.get("primaryGenreName")),
        "rating": _as_float(raw.get("averageUserRating")),
        "rating_count": _as_int(raw.get("userRatingCount")),
        "price": _as_text(raw.get("formattedPrice")),
        "version": _as_text(raw.get("version")),
        "url": _as_url(raw.get("trackViewUrl")),
    }


def _map_details(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one iTunes lookup object onto the canonical details record."""
    base = _map_app(raw)
    screenshots = raw.get("screenshotUrls")
    if not isinstance(screenshots, list):
        screenshots = []
    return {
        **base,
        "description": _as_text(raw.get("description")),
        "seller_name": _as_text(raw.get("sellerName")),
        "release_date": _as_text(raw.get("releaseDate")),
        "min_os": _as_text(raw.get("minimumOsVersion")),
        "size_bytes": _as_int(raw.get("fileSizeBytes")),
        "screenshots": [_as_text(s) for s in screenshots],
        "currency": _as_text(raw.get("currency")),
    }


def _map_review(entry: Any) -> dict[str, Any]:
    """Map one RSS ``feed.entry`` onto the canonical review record."""
    if not isinstance(entry, dict):
        return {}
    author = entry.get("author")
    author_name = author.get("name") if isinstance(author, dict) else author
    rating = _as_text(entry.get("rating"))
    return {
        "author": _as_text(author_name),
        "rating": _as_float(rating),
        "title": _as_text(entry.get("title")),
        "body": _as_text(entry.get("content")),
        "date": _as_text(entry.get("updated")),
        "version": _as_text(entry.get("im:version")),
    }


# ── Public API ────────────────────────────────────────────────────────
async def search_apps(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search the US App Store for software matching ``query``.

    Args:
        query: Search terms (e.g. ``"crypto wallet"``).
        limit: Max results (1-200; iTunes caps at 200).

    Returns:
        List of app records (see module docstring). ``[]`` on failure
        (blank query, network error, bad payload). Never raises.
    """
    try:
        return await _search_apps(query, limit)
    except Exception:
        logger.exception("appstore_apple_search_crashed", extra={"query": query})
        return []


async def _search_apps(query: str, limit: int) -> list[dict[str, Any]]:
    text = (query or "").strip()
    if not text:
        return []
    limit = max(1, min(int(limit), _MAX_LIMIT))
    payload = await _get_json(
        _SEARCH_URL,
        params={"term": text, "country": _COUNTRY, "entity": "software", "limit": limit},
    )
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    apps = [_map_app(r) for r in results if isinstance(r, dict)]
    return [a for a in apps if a.get("app_id") is not None][:limit]


async def get_app_details(app_id: int | str) -> dict[str, Any]:
    """Return details for a single App Store app by numeric id.

    Args:
        app_id: App Store numeric id (e.g. ``284882215``).

    Returns:
        Details dict (see module docstring), ``{}`` for unknown ids or on
        any failure. Never raises.
    """
    try:
        return await _get_app_details(app_id)
    except Exception:
        logger.exception("appstore_apple_details_crashed", extra={"app_id": app_id})
        return {}


async def _get_app_details(app_id: int | str) -> dict[str, Any]:
    if app_id in (None, ""):
        return {}
    payload = await _get_json(_LOOKUP_URL, params={"id": str(app_id).strip(), "country": _COUNTRY})
    if not isinstance(payload, dict):
        return {}
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return {}
    first = results[0]
    if not isinstance(first, dict):
        return {}
    return _map_details(first)


async def get_reviews(app_id: int | str, limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent customer reviews for an app (RSS feed).

    Args:
        app_id: App Store numeric id (e.g. ``284882215``).
        limit: Max reviews to return (1-200; the RSS feed serves up to 50).

    Returns:
        List of review records (see module docstring). ``[]`` on failure
        (unknown id, network error, bad payload). Never raises.
    """
    try:
        return await _get_reviews(app_id, limit)
    except Exception:
        logger.exception("appstore_apple_reviews_crashed", extra={"app_id": app_id})
        return []


async def _get_reviews(app_id: int | str, limit: int) -> list[dict[str, Any]]:
    if app_id in (None, ""):
        return []
    limit = max(1, min(int(limit), _MAX_LIMIT))
    url = _REVIEWS_URL_TMPL.format(app_id=str(app_id).strip())
    payload = await _get_json(url)
    if not isinstance(payload, dict):
        return []
    feed = payload.get("feed")
    if not isinstance(feed, dict):
        return []
    entry = feed.get("entry")
    entries: list[Any]
    if isinstance(entry, list):
        entries = entry
    elif isinstance(entry, dict):
        entries = [entry]  # single-review feed wraps entry as an object
    else:
        entries = []
    reviews = [_map_review(e) for e in entries]
    reviews = [r for r in reviews if r.get("author") or r.get("body")]
    return reviews[:limit]
