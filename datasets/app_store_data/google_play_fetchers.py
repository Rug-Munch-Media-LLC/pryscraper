"""Google Play fetchers — HTTP transport and public async API.

Anti-bot state (``last_anti_bot``) and the retry config are owned by the
``google_play`` facade module (tests patch them there), so they are
resolved lazily at call time.

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
from typing import Any

import httpx

from datasets.app_store_data.google_play_common import (
    _ANTI_BOT_MARKERS,
    _DETAILS_URL,
    _HEADERS,
    _MAGIC_PREFIX,
    _MAX_LIMIT,
    _REVIEWS_URL,
    _SEARCH_URL,
    _TIMEOUT,
    _AntiBotError,
    _extract_af_init,
    _extract_next_data,
    _find_app_entry,
    _is_app_entry,
    _iter_dicts,
    _iter_review_rows,
)
from datasets.app_store_data.google_play_parsers import (
    _map_app_entry,
    _map_details_entry,
    _map_review_row,
)
from pry.engine.retry import async_retry

logger = logging.getLogger(__name__)


def _facade() -> Any:
    """Return the facade module (lazy, to avoid a circular import)."""
    from datasets.app_store_data import google_play

    return google_play


# ── HTTP helpers ──────────────────────────────────────────────────────
def _detect_anti_bot(status_code: int, body: str) -> bool:
    """Return True when the response looks like an anti-bot/captcha page.

    Sets :data:`google_play.last_anti_bot` and logs a warning when detected.
    """
    lowered = (body or "").lower()
    detected = status_code in (403, 429, 503) or any(
        marker in lowered for marker in _ANTI_BOT_MARKERS
    )
    if detected:
        _facade().last_anti_bot = True
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
        return await async_retry(_one, config=_facade()._RETRY_CONFIG)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("google_play_fetch_failed", extra={"error": str(exc)[:120]})
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
        return await async_retry(_one, config=_facade()._RETRY_CONFIG)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("google_play_fetch_failed", extra={"error": str(exc)[:120]})
        return None
    except _AntiBotError:
        return None


# ── Public API ────────────────────────────────────────────────────────
async def search_apps(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search the US Google Play store for apps matching ``query``.

    Args:
        query: Search terms (e.g. ``"crypto wallet"``).
        limit: Max results (1-100).

    Returns:
        List of app records (see ``google_play`` docstring). ``[]`` on
        failure (blank query, network error, anti-bot page, bad payload).
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
        Details dict (see ``google_play`` docstring), ``{}`` for unknown
        packages or on any failure (including anti-bot). Never raises.
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
        List of review records (see ``google_play`` docstring). ``[]`` on
        failure (unknown package, network error, anti-bot page, bad
        payload). Never raises.
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
