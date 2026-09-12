"""News headlines + article extraction for Pry (real-time, free sources).

Thin re-export facade — implementation lives in focused sibling modules:

* :mod:`headlines_common` — shared helpers, endpoints, HTTP config.
* :mod:`headlines_fetchers` — GDELT/RSS fetching + parsing.
* :mod:`headlines_article` — full-article extraction via Pry's scraper.

Public API (unchanged contract):

* :func:`get_headlines` — async, never raises, returns a ``list`` (``[]`` on
  failure / no coverage).
* :func:`get_article` — async, never raises, returns a ``dict`` (``{}`` on
  invalid URL / scrape failure).

Both degrade honestly: no fake headlines, no fake article bodies.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.news_data.headlines_article import (  # noqa: F401 — test back-compat
    _extract_authors,
    _extract_published,
    _get_scraper,
    _keywords,
    _summarize,
    get_article,
)
from datasets.news_data.headlines_common import (  # noqa: F401 — back-compat re-exports
    _DEFAULT_LIMIT,
    _DEFAULT_TIMEFRAME,
    _GDELT_DOC_URL,
    _clamp_limit,
    _hostname,
    _parse_seendate,
    _sanitize_timeframe,
)
from datasets.news_data.headlines_fetchers import (  # noqa: F401 — back-compat re-exports
    _build_params,
    _fetch,
    _map_json_article,
    get_headlines,
)

__all__ = [
    "get_article",
    "get_headlines",
]
