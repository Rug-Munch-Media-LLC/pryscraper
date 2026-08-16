"""Legal / public-records package for Pry.

Aggregates the public functions of every submodule in this package so
consumers (MCP tools, x402-gated endpoints) can import them from a single
place:

* :mod:`legal_docs.dockets` — U.S. federal/state docket search and lookup
  via the free CourtListener REST API v4.
* :mod:`legal_docs.sec_filings` — SEC EDGAR company filings, single-filing
  lookup and insider-trade (Form 4) signals via the free EDGAR Full-Text
  Search API (``efts.sec.gov``) and the ``data.sec.gov`` submissions feed.
* :mod:`legal_docs.sanctions` — OFAC SDN sanctions-list name screening
  using the free OFAC SDN JSON/XML downloads (cached in-process and,
  optionally, on disk).

All functions are async and never raise — they return ``{}`` / ``[]`` on
failure (network error, 4xx/5xx, malformed payload, unknown entity). See
each module's docstring for the exact result shapes, the free-API terms and
the caching / backoff policy.

Example:
    >>> from legal_docs import (
    ...     get_docket,
    ...     get_filing,
    ...     insider_trades,
    ...     screen_name,
    ...     search_dockets,
    ...     search_filings,
    ... )
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from legal_docs.dockets import get_docket, search_dockets
from legal_docs.sanctions import screen_name
from legal_docs.sec_filings import get_filing, insider_trades, search_filings

__all__ = [
    "get_docket",
    "get_filing",
    "insider_trades",
    "screen_name",
    "search_dockets",
    "search_filings",
]
