"""Research data package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`research_data.academic` — scholarly search via OpenAlex (CC0,
  keyless) with Crossref fallback: papers by keyword, single-paper lookup.
* :mod:`research_data.domain` — domain intelligence via RDAP (keyless
  WHOIS replacement) + crt.sh Certificate Transparency logs.

All functions are async and never raise — they return ``[]`` / ``{}`` /
partial dicts on failure. See each module's docstring for the exact
result shapes.

Example:
    >>> from research_data import cert_transparency, search_papers, whois_lookup
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from research_data.academic import get_paper, search_papers
from research_data.domain import cert_transparency, whois_lookup

__all__ = [
    "cert_transparency",
    "get_paper",
    "search_papers",
    "whois_lookup",
]
