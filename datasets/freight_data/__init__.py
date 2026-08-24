"""Freight / logistics data package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`freight_data.rates` — container freight intelligence:
  :func:`get_container_rates` (40ft spot rates from the Freightos Baltic
  Index, with a Drewry World Container Index scrape fallback) and
  :func:`get_fmc_contracts` (agreements on file at the U.S. Federal
  Maritime Commission Agreement Library).

All functions are async and never raise — they return ``[]`` / ``{}`` /
``None`` on failure. See each module's docstring for the exact result
shapes.

Example:
    >>> from freight_data import get_container_rates, get_fmc_contracts
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.freight_data.rates import get_container_rates, get_fmc_contracts

__all__ = [
    "get_container_rates",
    "get_fmc_contracts",
]
