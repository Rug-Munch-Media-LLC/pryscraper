"""Climate data package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`climate_data.weather` — NOAA NWS weather: current conditions,
  daily forecast and active alerts for a lat/lon point (free, no auth).
* :mod:`climate_data.agri` — USDA NASS crop prices received, via the
  QuickStats API (free key optional via ``PRY_NASS_API_KEY``).

All functions are async and never raise — they return ``[]`` / ``{}`` /
partial dicts on failure. See each module's docstring for the exact
result shapes.

Example:
    >>> from climate_data import get_alerts, get_crop_prices, get_forecast
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.climate_data.agri import get_crop_prices
from datasets.climate_data.weather import get_alerts, get_forecast

__all__ = [
    "get_alerts",
    "get_crop_prices",
    "get_forecast",
]
