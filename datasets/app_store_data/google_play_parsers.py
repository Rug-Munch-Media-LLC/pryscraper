"""Google Play record mappers — embedded-JSON entries to canonical records.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from datasets.app_store_data.google_play_common import (
    _STORE_URL_TMPL,
    _as_float,
    _as_int,
    _as_text,
    _format_price,
)


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
