"""NOAA NWS weather data — free, no auth, no API key.

Backed by the National Weather Service API (https://api.weather.gov),
which is a free public API that requires no key and no signup. The only
requirement is a descriptive ``User-Agent`` header (set below).

Contract
--------
* :func:`get_forecast` — async, never raises, returns a ``dict`` (``{}``
  on failure). Returns current conditions + ``days`` of daily forecast
  + active alerts for the point.
* :func:`get_alerts` — async, never raises, returns a ``list`` (``[]``
  on failure). Fetches active alerts for a zone id, a state, or a point.

Location format
---------------
``location`` is ``"lat,lon"`` (decimal degrees, e.g. ``"38.9072,-77.0369"``).
NWS does not geocode; unparseable input degrades to ``{}`` / ``[]``.

Result shapes
-------------
``get_forecast`` returns::

    {
        "location": {"lat": 38.9072, "lon": -77.0369, "city": "Washington", "state": "DC"},
        "current": {"temp_f": 88.0, "condition": "Sunny", "wind_mph": 8.0,
                    "humidity_pct": 45.0, "observed_at": "2026-08-16T18:53:00+00:00"},
        "forecast": [{"date": "2026-08-16", "high_f": 92, "low_f": 72,
                      "condition": "Sunny", "precip_pct": 10}],
        "alerts": [{"id": "...", "event": "Heat Advisory", "severity": "Moderate",
                    "headline": "...", "effective": "...", "expires": "...", "areas": "DC"}],
    }

``get_alerts`` returns a list of the same alert records shown above.

Free-API terms: https://www.weather.gov/documentation/services-web-api — 5k
req/day default, generous. Backoff: 2 retries, exponential (0.4s -> 1.6s).

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
from datetime import datetime
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_API_ROOT = "https://api.weather.gov"
_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-climate/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/geo+json, application/json",
}
_MAX_DAYS = 14


def _parse_location(location: str) -> tuple[float, float] | None:
    """Parse ``"lat,lon"`` into floats, or None when unparseable."""
    if not location or not location.strip():
        return None
    parts = location.strip().split(",")
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0].strip())
        lon = float(parts[1].strip())
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> float | None:
    """Coerce a JSON value to float/None ('' -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_from_iso(value: Any) -> str:
    """Extract ``YYYY-MM-DD`` from an ISO-8601 string, or '' on failure."""
    text = _as_text(value)
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10]


def _map_alert(feature: dict[str, Any]) -> dict[str, Any]:
    """Map one NWS alerts GeoJSON feature onto the canonical alert record."""
    props = feature.get("properties")
    if not isinstance(props, dict):
        return {}
    return {
        "id": _as_text(props.get("id")) or _as_text(feature.get("id")),
        "event": _as_text(props.get("event")),
        "severity": _as_text(props.get("severity")),
        "headline": _as_text(props.get("headline")),
        "description": _as_text(props.get("description")),
        "effective": _as_text(props.get("effective")),
        "expires": _as_text(props.get("expires")),
        "areas": _as_text(props.get("areaDesc")),
        "source": "noaa_nws",
    }


def _map_periods(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse NWS daily periods into ``{date, high_f, low_f, condition, precip_pct}``.

    NWS alternates daytime/nighttime periods; group by calendar date and
    keep the day high / night low. A date with only one period uses what
    it has (high for day, low for night).
    """
    by_date: dict[str, dict[str, Any]] = {}
    for raw in periods:
        if not isinstance(raw, dict):
            continue
        date = _date_from_iso(raw.get("startTime"))
        if not date:
            continue
        temp = _as_float(raw.get("temperature"))
        precip = raw.get("probabilityOfPrecipitation")
        precip_pct = _as_float(precip.get("value")) if isinstance(precip, dict) else None
        is_day = bool(raw.get("isDaytime"))
        record = by_date.setdefault(
            date,
            {"date": date, "high_f": None, "low_f": None, "condition": None, "precip_pct": None},
        )
        if is_day:
            if temp is not None:
                record["high_f"] = temp
            record["condition"] = _as_text(raw.get("shortForecast")) or record["condition"]
        else:
            if temp is not None:
                record["low_f"] = temp
            record["condition"] = record["condition"] or _as_text(raw.get("shortForecast"))
        day_precip = record["precip_pct"]
        if precip_pct is not None:
            record["precip_pct"] = precip_pct if day_precip is None else max(day_precip, precip_pct)
    return list(by_date.values())


async def _get_json(url: str) -> dict[str, Any] | None:
    """GET ``url`` and return its JSON object, or None on any failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"expected JSON object at {url}")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_current(stations_url: str) -> dict[str, Any]:
    """Fetch the latest observation from the point's first station."""
    stations = await _get_json(stations_url)
    if not stations:
        return {}
    station_list = stations.get("features")
    if not isinstance(station_list, list) or not station_list:
        return {}
    first = station_list[0]
    station_id = first.get("id") if isinstance(first, dict) else None
    if not station_id:
        return {}
    obs = await _get_json(f"{station_id}/observations/latest")
    props = obs.get("properties") if isinstance(obs, dict) else None
    if not isinstance(props, dict):
        return {}
    temperature = props.get("temperature")
    temp_c = _as_float(temperature.get("value")) if isinstance(temperature, dict) else None
    wind = props.get("windSpeed")
    wind_kmh = _as_float(wind.get("value")) if isinstance(wind, dict) else None
    humidity = props.get("relativeHumidity")
    humidity_pct = _as_float(humidity.get("value")) if isinstance(humidity, dict) else None
    return {
        "temp_f": round(temp_c * 9.0 / 5.0 + 32.0, 1) if temp_c is not None else None,
        "condition": _as_text(props.get("textDescription")),
        "wind_mph": round(wind_kmh * 0.621371, 1) if wind_kmh is not None else None,
        "humidity_pct": humidity_pct,
        "observed_at": _as_text(props.get("timestamp")),
    }


async def _fetch_alerts_for_point(lat: float, lon: float) -> list[dict[str, Any]]:
    """Fetch active alerts for a lat/lon point (via the NWS point URL)."""
    point = await _get_json(f"{_API_ROOT}/points/{lat},{lon}")
    if not point:
        return []
    zone = (
        point.get("properties", {}).get("forecastZone")
        if isinstance(point.get("properties"), dict)
        else None
    )
    if not zone:
        return []
    # forecastZone is a URL like https://api.weather.gov/zones/forecast/DCZ001
    return await get_alerts(str(zone).split("/")[-1])


# ── Public API ─────────────────────────────────────────────────────────
async def get_forecast(location: str, days: int = 7) -> dict[str, Any]:
    """Return current conditions, daily forecast and alerts for a point.

    Args:
        location: ``"lat,lon"`` decimal degrees (e.g. ``"38.9072,-77.0369"``).
        days: Max forecast days to return (1-14; NWS usually serves ~7).

    Returns:
        Dict with ``location`` / ``current`` / ``forecast`` / ``alerts``
        (see module docstring). ``{}`` on failure. Never raises.
    """
    try:
        return await _get_forecast(location, days)
    except Exception:
        logger.exception("noaa_weather_forecast_crashed", extra={"location": location})
        return {}


async def _get_forecast(location: str, days: int) -> dict[str, Any]:
    parsed = _parse_location(location)
    if parsed is None:
        logger.warning("noaa_weather_bad_location", extra={"location": location})
        return {}
    lat, lon = parsed
    days = max(1, min(int(days), _MAX_DAYS))
    point = await _get_json(f"{_API_ROOT}/points/{lat},{lon}")
    if not point:
        return {}
    properties = point.get("properties")
    if not isinstance(properties, dict):
        return {}
    forecast_url = properties.get("forecast")
    relative = properties.get("relativeLocation")
    relative_props = relative.get("properties") if isinstance(relative, dict) else None
    city = _as_text(relative_props.get("city")) if isinstance(relative_props, dict) else None
    state = _as_text(relative_props.get("state")) if isinstance(relative_props, dict) else None

    periods: list[dict[str, Any]] = []
    if isinstance(forecast_url, str):
        forecast = await _get_json(forecast_url)
        if isinstance(forecast, dict):
            props = forecast.get("properties")
            raw_periods = props.get("periods") if isinstance(props, dict) else None
            if isinstance(raw_periods, list):
                periods = _map_periods(raw_periods)

    current: dict[str, Any] = {}
    station_url = properties.get("observationStations")
    if isinstance(station_url, str):
        current = await _fetch_current(station_url)

    alerts = await _fetch_alerts_for_point(lat, lon)

    return {
        "location": {"lat": lat, "lon": lon, "city": city, "state": state},
        "current": current,
        "forecast": periods[:days],
        "alerts": alerts,
    }


async def get_alerts(region: str) -> list[dict[str, Any]]:
    """Fetch active NWS alerts for a zone, state, or lat/lon point.

    Args:
        region: A zone id (e.g. ``"DCZ001"``), a state/territory code
            (e.g. ``"DC"``), or ``"lat,lon"``.

    Returns:
        List of alert records (see module docstring). ``[]`` on failure.
        Never raises.
    """
    try:
        return await _get_alerts(region)
    except Exception:
        logger.exception("noaa_weather_alerts_crashed", extra={"region": region})
        return []


async def _get_alerts(region: str) -> list[dict[str, Any]]:
    text = (region or "").strip()
    if not text:
        return []
    parsed = _parse_location(text)
    if parsed is not None:
        lat, lon = parsed
        params = {"point": f"{lat},{lon}"}
    elif any(ch.isdigit() for ch in text) and any(ch.isalpha() for ch in text) and len(text) <= 8:
        # Zone ids look like "DCZ001" / "MOZ028" (letters + digits, short).
        params = {"zone": text.upper()}
    else:
        params = {"area": text.upper()}

    async def _one() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(f"{_API_ROOT}/alerts/active", params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("NWS alerts payload is not an object")
        features = payload.get("features")
        if not isinstance(features, list):
            raise ValueError("NWS alerts payload missing features list")
        return features

    try:
        features = await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return []
    return [alert for alert in (_map_alert(f) for f in features if isinstance(f, dict)) if alert]
