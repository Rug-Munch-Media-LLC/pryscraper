"""Energy markets data package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`energy_data.lmp` — ISO day-ahead locational marginal prices (LMP)
  from the NYISO MIS public CSV archive (keyless) + PJM Data Miner 2
  (free key) + an optional ``gridstatus`` fast-path for ERCOT/CAISO, and
  weekly retail fuel prices (gasoline / diesel) via the EIA v2 API.

All functions are async and never raise — they return ``[]`` / ``{}`` /
partial dicts on failure. See each module's docstring for the exact
result shapes.

Example:
    >>> from energy_data import get_fuel_prices, get_lmp
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from energy_data.lmp import get_fuel_prices, get_lmp

__all__ = [
    "get_fuel_prices",
    "get_lmp",
]
