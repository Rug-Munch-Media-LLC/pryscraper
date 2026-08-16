"""County assessor property records — free public ArcGIS REST services.

County assessor / parcel data is exposed by many US counties through free,
key-less Esri ArcGIS REST ``FeatureServer`` endpoints. This module queries
those endpoints for parcel/property records by parcel id.

Counties
--------
A small registry of known, verified county endpoints ships with the module
(see :data:`ARCGIS_COUNTIES`). The canonical example is **Wake County, NC**
(``wake-nc``), whose public Parcels FeatureServer was verified live:

    https://maps.wakegov.com/arcgis/rest/services/Property/Parcels/FeatureServer/0

* :attr:`~dict` ``wake-nc`` — Wake County, NC — ``PIN_NUM`` parcel ids.

Additional counties can be added at runtime without code changes via the
``PRY_REAL_ESTATE_ARCGIS_URLS`` env var (JSON mapping a county key to
``{"url", "id_field", ...}``), e.g.::

    PRY_REAL_ESTATE_ARCGIS_URLS='{"my-county": {"url": "https://gis.example.gov/arcgis/rest/services/Parcels/FeatureServer/0", "id_field": "PARCEL_ID"}}'

Contract
--------
* :func:`get_property` is async, never raises, and returns ``{}`` on failure
  (unknown county, network error, parcel not found).

Result shape (``wake-nc`` populated where the source provides the field):

    {
        "parcel_id": "0695327712",
        "owner": "GURRAM, ANANDA PAPIREDDY, MURALIDHAR REDDY",
        "assessed_value": 619967,
        "tax": null,            # parcel services rarely carry tax amounts
        "sale_history": [{"price": 795000, "sale_date": "2024-12-16T00:00:00Z", ...}],
        "county": "Wake County, North Carolina",
        "source": "arcgis",
        "details": {...},
    }

robots.txt + backoff follow the same policy as :mod:`real_estate.listings`
(robots checked/surfaced; ``PRY_REAL_ESTATE_ENFORCE_ROBOTS=1`` hard-blocks).

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
import os
from datetime import UTC, datetime
from typing import Any

import httpx

# Shared robots.txt / HTTP helpers live in listings.py (same package, same
# policy) — re-exported here so property records and listings stay in sync.
from real_estate.listings import _robots_allowed, _sleep_for_robots
from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(12.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pry-property-records/1.0)",
    "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
}

_ARCGIS_URLS_ENV = "PRY_REAL_ESTATE_ARCGIS_URLS"

# Known, verified county assessor / parcel ArcGIS REST endpoints.
# ``fields`` is the outFields list; ``assessed_value_field`` /
# ``sale_price_field`` / ``sale_date_field`` / ``owner_field`` map the parcel
# attributes onto the canonical record. Field sets are service-specific.
ARCGIS_COUNTIES: dict[str, dict[str, Any]] = {
    "wake-nc": {
        "name": "Wake County, North Carolina",
        "url": "https://maps.wakegov.com/arcgis/rest/services/Property/Parcels/FeatureServer/0",
        "id_field": "PIN_NUM",
        "owner_field": "OWNER",
        "assessed_value_field": "TOTAL_VALUE_ASSD",
        "sale_price_field": "TOTSALPRICE",
        "sale_date_field": "SALE_DATE",
        "fields": [
            "PIN_NUM",
            "OWNER",
            "TOTAL_VALUE_ASSD",
            "TOTSALPRICE",
            "SALE_DATE",
            "DEED_BOOK",
            "DEED_PAGE",
            "DEED_DATE",
            "DEED_ACRES",
            "SITE_ADDRESS",
            "CITY",
            "YEAR_BUILT",
            "HEATEDAREA",
            "PROPDESC",
            "BILLING_CLASS_DECODE",
        ],
        "extra_fields": {
            "site_address": "SITE_ADDRESS",
            "city": "CITY",
            "year_built": "YEAR_BUILT",
            "heated_area": "HEATEDAREA",
            "deed_book": "DEED_BOOK",
            "deed_page": "DEED_PAGE",
            "deed_date": "DEED_DATE",
            "deed_acres": "DEED_ACRES",
            "property_description": "PROPDESC",
            "billing_class": "BILLING_CLASS_DECODE",
        },
    },
}

# Fallback id field when a runtime county config omits ``id_field``.
_DEFAULT_ID_FIELD = "PARCEL_ID"


def _county_registry() -> dict[str, dict[str, Any]]:
    """Known counties merged with any ``PRY_REAL_ESTATE_ARCGIS_URLS`` extras."""
    registry = {key: dict(cfg) for key, cfg in ARCGIS_COUNTIES.items()}
    raw = os.environ.get(_ARCGIS_URLS_ENV)
    if not raw:
        return registry
    try:
        extra = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("real_estate_arcgis_env_invalid")
        return registry
    if not isinstance(extra, dict):
        return registry
    for key, cfg in extra.items():
        if isinstance(cfg, dict) and cfg.get("url"):
            registry[str(key).strip().lower()] = cfg
        else:
            logger.warning("real_estate_arcgis_env_skip", extra={"county": key})
    return registry


def _county_key(county: str) -> str:
    """Normalize a county name to a registry key (``wake, nc`` -> ``wake-nc``)."""
    return county.strip().lower().replace("_", "-").replace(" ", "-").replace(",", "")


def _epoch_millis_to_iso(value: Any) -> str | None:
    """Convert an ArcGIS epoch-millis date to ISO-8601 UTC (``None`` when bad)."""
    if value is None:
        return None
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    try:
        return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _to_number(value: Any) -> int | float | None:
    """Best-effort numeric conversion (ArcGIS returns int/float or None)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


async def _arcgis_query(cfg: dict[str, Any], parcel_id: str) -> dict[str, Any] | None:
    """Run an ArcGIS FeatureServer query; return the first feature's attributes."""
    id_field = str(cfg.get("id_field") or _DEFAULT_ID_FIELD)
    escaped = str(parcel_id).replace("'", "''")
    fields = cfg.get("fields") or ["*"]
    params = {
        "where": f"{id_field}='{escaped}'",
        "outFields": ",".join(str(f) for f in fields),
        "returnGeometry": "false",
        "resultRecordCount": "1",
        "f": "json",
    }
    url = f"{cfg['url']}/query"

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("arcgis payload is not an object")
        return payload

    try:
        payload = await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError):
        return None
    features = payload.get("features") or []
    if not isinstance(features, list) or not features:
        return None
    attributes = features[0].get("attributes") if isinstance(features[0], dict) else None
    return attributes if isinstance(attributes, dict) else None


def _build_record(cfg: dict[str, Any], parcel_id: str, attrs: dict[str, Any]) -> dict[str, Any]:
    """Map ArcGIS parcel attributes onto the canonical property record."""
    id_field = str(cfg.get("id_field") or _DEFAULT_ID_FIELD)
    sale_history: list[dict[str, Any]] = []
    sale_price = _to_number(attrs.get(str(cfg.get("sale_price_field") or "")))
    sale_date = _epoch_millis_to_iso(attrs.get(str(cfg.get("sale_date_field") or "")))
    if sale_price is not None or sale_date is not None:
        sale_history.append(
            {
                "price": sale_price,
                "sale_date": sale_date,
                "deed_book": attrs.get("DEED_BOOK"),
                "deed_page": attrs.get("DEED_PAGE"),
                "source": "county_assessor",
            }
        )
    details: dict[str, Any] = {}
    for target, source_field in (cfg.get("extra_fields") or {}).items():
        value = attrs.get(str(source_field))
        if value is not None:
            details[target] = value
    return {
        "parcel_id": str(attrs.get(id_field) or parcel_id),
        "owner": attrs.get(str(cfg.get("owner_field") or "OWNER")),
        "assessed_value": _to_number(attrs.get(str(cfg.get("assessed_value_field") or ""))),
        "tax": None,  # parcel FeatureServers rarely carry tax amounts (see docs)
        "sale_history": sale_history,
        "county": str(cfg.get("name") or ""),
        "source": "arcgis",
        "robots_allowed": True,
        "details": details,
    }


# ── Public API ─────────────────────────────────────────────────────────
async def get_property(parcel_id: str, county: str) -> dict[str, Any]:
    """Look up a property record by parcel id in a county assessor service.

    Args:
        parcel_id: County parcel / PIN number (e.g. Wake County ``0695327712``).
        county: Registry key or county name (e.g. ``"wake-nc"`` / ``"wake, nc"``).

    Returns:
        ``{parcel_id, owner, assessed_value, tax, sale_history}`` plus county /
        source / details extras. ``{}`` on unknown county, network failure, or
        parcel not found. Never raises.
    """
    try:
        return await _get_property(parcel_id, county)
    except Exception:
        logger.exception("real_estate_get_property_crashed")
        return {}


async def _get_property(parcel_id: str, county: str) -> dict[str, Any]:
    key = _county_key(county)
    cfg = _county_registry().get(key)
    if cfg is None:
        logger.warning("real_estate_unknown_county", extra={"county": county})
        return {}
    url = str(cfg["url"])
    if not await _robots_allowed(url):
        if os.environ.get("PRY_REAL_ESTATE_ENFORCE_ROBOTS", "0") == "1":
            logger.warning("real_estate_robots_blocked", extra={"url": url})
            return {}
        logger.warning("real_estate_robots_disallowed_fetching", extra={"url": url})
    await _sleep_for_robots(url)
    attrs = await _arcgis_query(cfg, parcel_id)
    if attrs is None:
        return {}
    record = _build_record(cfg, parcel_id, attrs)
    record["robots_allowed"] = True
    return record
