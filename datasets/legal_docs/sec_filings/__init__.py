"""SEC EDGAR company filings, lookup, and insider-trade signals.

The package keeps the historical import path while separating transport,
identifier handling, ticker caching, filing search, filing lookup, and Form 4
enrichment into focused modules. Public functions remain asynchronous and
degrade to empty results instead of raising.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from datasets.legal_docs.sec_filings.filings import get_filing
from datasets.legal_docs.sec_filings.insider import insider_trades
from datasets.legal_docs.sec_filings.search import search_filings
from datasets.legal_docs.sec_filings.tickers import reset_ticker_cache
from datasets.legal_docs.sec_filings.transport import configure_retries

__all__ = [
    "configure_retries",
    "get_filing",
    "insider_trades",
    "reset_ticker_cache",
    "search_filings",
]
