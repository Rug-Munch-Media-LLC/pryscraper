# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Turn a scrape exception into a bounded ``reason`` label.

The scrape counter only knew ``success`` / ``error``, so "27% of scrapes fail"
could never be attributed. ``ScrapeError`` already carries the engine's verdict
(``blocked`` / ``exhausted`` / ``unavailable``); everything else is classified
by exception type. Labels are bounded on purpose — a metric must not carry a
free-text message, or the cardinality explodes.
"""

from __future__ import annotations

import httpx

from pry.core.errors import PryError, ScrapeError

VERDICTS = frozenset({"blocked", "exhausted", "unavailable"})


def classify_failure(exc: BaseException) -> str:
    """Return a low-cardinality reason for a failed scrape."""
    if isinstance(exc, ScrapeError):
        verdict = (exc.verdict or "").strip()
        return verdict if verdict in VERDICTS else "chain_failed"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect"
    if isinstance(exc, httpx.HTTPError):
        return "http"
    if isinstance(exc, PryError):
        return str(getattr(exc, "code", "") or "pry_error")
    return "exception"
