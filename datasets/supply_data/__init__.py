"""Supply-chain + B2B lead-gen package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`supply_data.imports` — ImportYeti/Panjiva-style company import
  records (bill-of-lading flavour: HS code, product, origin, consignee,
  shipment date, quantity, TEU). A partner API key is required
  (``PRY_IMPORTS_API_KEY`` / ``PRY_IMPORTS_API_URL``); without one the
  module degrades to ``[]`` and logs the login/anti-bot wall honestly.
* :mod:`supply_data.firmographics` — B2B firmographics for a company
  (website, tech stack, industry, LinkedIn URL, hiring-openings count
  from public job boards, funding/headcount via a Crunchbase-adjacent
  partner API when configured). All fields degrade to ``None`` /
  ``0`` / ``[]`` independently — never raises.

All functions are async and never raise — they return ``[]`` / ``{}`` /
partial dicts on failure. See each module's docstring for the exact
result shapes.

Example:
    >>> from supply_data import get_company_firmographics, get_import_records
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.supply_data.firmographics import get_company_firmographics
from datasets.supply_data.imports import get_import_records

__all__ = [
    "get_company_firmographics",
    "get_import_records",
]
