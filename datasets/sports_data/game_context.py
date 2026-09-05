"""Game-context dataset: weather, rest, and travel context for matchups.

Async, never raises, returns ``{}`` on failure. Weather: Open-Meteo
(free, no key). Rest days: ESPN scoreboard. Travel: static venue table.

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
import math
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
_ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{slug}/scoreboard"
_TIMEOUT = httpx.Timeout(10.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

# sport → ESPN scoreboard slug
_ESPN_SLUGS = {
    "nba": "basketball/nba",
    "nfl": "football/nfl",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
    "ncaab": "basketball/mens-college-basketball",
    "ncaaf": "football/college-football",
    "wnba": "basketball/wnba",
}

# team name fragment → (lat, lon, utc_offset_hours, elevation_m)
# Compact venue table for the major pro franchises (home venues).
_TEAM_VENUES: dict[str, tuple[float, float, int, int]] = {
    "arizona": (33.53, -112.19, -7, 335),
    "atlanta": (33.75, -84.40, -5, 320),
    "baltimore": (39.28, -76.62, -5, 10),
    "boston": (42.09, -71.26, -5, 25),
    "buffalo": (42.77, -78.75, -5, 185),
    "calgary": (51.03, -114.05, -6, 1045),
    "charlotte": (35.23, -80.85, -5, 220),
    "chicago": (41.88, -87.63, -6, 180),
    "cincinnati": (39.10, -84.52, -5, 145),
    "cleveland": (41.51, -81.68, -5, 200),
    "colorado": (39.74, -105.02, -7, 1609),
    "dallas": (32.75, -97.09, -6, 150),
    "denver": (39.74, -105.02, -7, 1609),
    "detroit": (42.34, -83.05, -5, 185),
    "edmonton": (53.52, -113.50, -7, 668),
    "green bay": (44.50, -88.06, -6, 240),
    "houston": (29.68, -95.41, -6, 15),
    "indiana": (39.76, -86.16, -5, 220),
    "jacksonville": (30.32, -81.68, -5, 5),
    "kansas city": (39.05, -94.48, -6, 260),
    "las vegas": (36.09, -115.18, -8, 610),
    "los angeles": (33.95, -118.34, -8, 30),
    "miami": (25.96, -80.24, -5, 3),
    "milwaukee": (43.04, -87.97, -6, 190),
    "minnesota": (44.98, -93.26, -6, 255),
    "montreal": (45.50, -73.57, -5, 35),
    "nashville": (36.16, -86.77, -6, 110),
    "new jersey": (40.68, -74.07, -5, 15),
    "new orleans": (29.95, -90.08, -6, 3),
    "new york": (40.75, -73.99, -5, 15),
    "oklahoma": (35.46, -97.52, -6, 360),
    "orlando": (28.54, -81.38, -5, 25),
    "ottawa": (45.42, -75.67, -5, 70),
    "philadelphia": (39.90, -75.17, -5, 12),
    "phoenix": (33.45, -112.07, -7, 335),
    "pittsburgh": (40.45, -80.00, -5, 230),
    "raleigh": (35.78, -78.72, -5, 120),
    "sacramento": (38.58, -121.50, -8, 10),
    "san antonio": (29.43, -98.43, -6, 200),
    "san diego": (32.78, -117.15, -8, 15),
    "san francisco": (37.75, -122.20, -8, 15),
    "seattle": (47.60, -122.33, -8, 5),
    "st. louis": (38.63, -90.21, -6, 140),
    "tampa bay": (27.76, -82.63, -5, 5),
    "tennessee": (36.17, -86.77, -6, 110),
    "toronto": (43.63, -79.42, -5, 76),
    "utah": (40.77, -111.90, -7, 1288),
    "vancouver": (49.28, -123.11, -8, 5),
    "washington": (38.90, -77.01, -5, 15),
    "winnipeg": (49.89, -97.14, -6, 236),
}


def _venue_of(team: str) -> tuple[float, float, int, int] | None:
    """Look up a team's venue tuple by name fragment (case-insensitive)."""
    needle = str(team or "").strip().lower()
    if not needle:
        return None
    for fragment, venue in _TEAM_VENUES.items():
        if fragment in needle or needle in fragment:
            return venue
    return None


async def _get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    """GET JSON, returning ``None`` on any failure (never raises)."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.debug("game_context fetch failed for %s: %s", url, exc)
        return None


def _num(value: Any) -> float | None:
    """Coerce a JSON value to float or None."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ── Weather ────────────────────────────────────────────────────────────
async def get_game_weather(lat: float, lon: float) -> dict[str, Any]:
    """Current weather at a venue via Open-Meteo. ``{}`` on failure."""
    if lat is None or lon is None:
        return {}
    payload = await _get_json(
        _OPEN_METEO,
        {
            "latitude": lat,
            "longitude": lon,
            "current": (
                "temperature_2m,wind_speed_10m,precipitation,relative_humidity_2m,visibility"
            ),
        },
    )
    current = payload.get("current") if isinstance(payload, dict) else None
    if not isinstance(current, dict):
        return {}
    temp_c = _num(current.get("temperature_2m"))
    wind_kmh = _num(current.get("wind_speed_10m"))
    vis_m = _num(current.get("visibility"))
    temp_f = temp_c * 9 / 5 + 32 if temp_c is not None else None
    wind_mph = wind_kmh * 0.621371 if wind_kmh is not None else None
    visibility = vis_m / 1609.34 if vis_m is not None else None
    precip = _num(current.get("precipitation")) or 0.0
    humidity = _num(current.get("relative_humidity_2m"))
    summary = "clear"
    if precip >= 2.5:
        summary = "heavy precipitation"
    elif precip > 0:
        summary = "precipitation"
    elif wind_mph is not None and wind_mph >= 20:
        summary = "windy"
    return {
        "temp_f": round(temp_f, 1) if temp_f is not None else None,
        "wind_mph": round(wind_mph, 1) if wind_mph is not None else None,
        "precipitation": precip,
        "humidity": humidity,
        "visibility": round(visibility, 2) if visibility is not None else None,
        "conditions_summary": summary,
    }


def _impact_band(value: float | None, thresholds: tuple[float, float]) -> str:
    """Map a value onto low/med/high via (med_threshold, high_threshold)."""
    if value is None:
        return "unknown"
    med, high = thresholds
    if value >= high:
        return "high"
    if value >= med:
        return "med"
    return "low"


async def get_weather_impact(lat: float, lon: float, sport: str = "nfl") -> dict[str, Any]:
    """Translate venue weather into scoring/pass/run adjustments."""
    weather = await get_game_weather(lat, lon)
    if not weather:
        return {}
    wind = weather.get("wind_mph")
    temp_f = weather.get("temp_f")
    precip = weather.get("precipitation") or 0.0
    wind_impact = _impact_band(wind, (12.0, 20.0))
    temp_impact = (
        "cold"
        if temp_f is not None and temp_f <= 32
        else ("heat" if temp_f is not None and temp_f >= 90 else "neutral")
    )
    precip_impact = _impact_band(precip, (0.5, 2.0))
    total = 0.0
    if wind_impact == "high":
        total -= 4.0
    elif wind_impact == "med":
        total -= 1.5
    if precip_impact == "high":
        total -= 3.5
    elif precip_impact == "med":
        total -= 1.0
    if temp_impact == "cold":
        total -= 2.0
    elif temp_impact == "heat":
        total -= 1.0
    pass_hit = wind_impact == "high" or precip_impact != "low"
    run_hit = wind_impact != "low" or precip_impact != "low"
    return {
        "sport": sport,
        "wind_impact": wind_impact,
        "temp_impact": temp_impact,
        "precip_impact": precip_impact,
        "total_adjustment": round(total, 1),
        "pass_game_impact": "negative" if pass_hit else "neutral",
        "run_game_impact": "positive" if run_hit else "neutral",
        "weather": weather,
    }


# ── Rest ───────────────────────────────────────────────────────────────
def _last_game_date(payload: dict[str, Any], team: str) -> datetime | None:
    """Find the most recent completed game date for ``team`` in a scoreboard."""
    needle = str(team or "").strip().lower()
    if not needle:
        return None
    best: datetime | None = None
    for event in payload.get("events") or []:
        status = (event.get("status") or {}).get("type") or {}
        if str(status.get("state", "")).lower() != "post":
            continue
        competitors = ((event.get("competitions") or [{}])[0].get("competitors")) or []
        for comp in competitors:
            name = str((comp.get("team") or {}).get("displayName", "")).lower()
            if needle not in name and name not in needle:
                continue
            raw = event.get("date")
            try:
                played = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if best is None or played > best:
                best = played
    return best


async def get_rest_advantage(home_team: str, away_team: str, sport: str = "nba") -> dict[str, Any]:
    """Days since each team's last completed game, via ESPN scoreboard."""
    slug = _ESPN_SLUGS.get(str(sport).lower())
    if not slug:
        return {}
    payload = await _get_json(_ESPN_SCOREBOARD.format(slug=slug))
    if not isinstance(payload, dict):
        return {}
    now = datetime.now(UTC)
    home_rest = away_rest = None
    if last := _last_game_date(payload, home_team):
        home_rest = max(0, (now - last).days)
    if last := _last_game_date(payload, away_team):
        away_rest = max(0, (now - last).days)
    if home_rest is None and away_rest is None:
        return {}
    advantage = None
    if home_rest is not None and away_rest is not None:
        advantage = home_rest - away_rest
    return {
        "sport": sport,
        "home_rest_days": home_rest,
        "away_rest_days": away_rest,
        "rest_advantage": advantage,
        "home_back_to_back": home_rest == 0,
        "away_back_to_back": away_rest == 0,
    }


# ── Travel ─────────────────────────────────────────────────────────────
def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in miles."""
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def get_travel_context(home_team: str, away_team: str) -> dict[str, Any]:
    """Distance / time-zone / altitude change between two teams' venues."""
    home, away = _venue_of(home_team), _venue_of(away_team)
    if home is None or away is None:
        return {}
    hlat, hlon, htz, halt = home
    alat, alon, atz, aalt = away
    return {
        "home_team": home_team,
        "away_team": away_team,
        "travel_distance": round(_haversine_miles(hlat, hlon, alat, alon)),
        "time_zone_change": abs(htz - atz),
        "altitude_change": abs(halt - aalt),
    }


# ── Bundle ─────────────────────────────────────────────────────────────
async def get_game_context(
    lat: float,
    lon: float,
    home_team: str,
    away_team: str,
    sport: str = "nfl",
) -> dict[str, Any]:
    """Full game-context bundle: weather + impact + rest + travel."""
    import asyncio

    results = await asyncio.gather(
        get_game_weather(lat, lon),
        get_weather_impact(lat, lon, sport),
        get_rest_advantage(home_team, away_team, sport),
        get_travel_context(home_team, away_team),
        return_exceptions=True,
    )
    weather, impact, rest, travel = (r if isinstance(r, dict) else {} for r in results)
    if not (weather or impact or rest or travel):
        return {}
    return {
        "sport": sport,
        "home_team": home_team,
        "away_team": away_team,
        "weather": weather,
        "weather_impact": impact,
        "rest": rest,
        "travel": travel,
    }
