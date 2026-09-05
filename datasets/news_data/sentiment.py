"""News sentiment + entity timelines for Pry (free, no-auth sources).

Thin re-export facade — implementation lives in:

* :mod:`datasets.news_data.sentiment_common` — lexicons + tone scoring
* :mod:`datasets.news_data.sentiment_fetchers` — GDELT artlist fetch/parse
* :mod:`datasets.news_data.sentiment_analysis` — aggregation + timelines

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.news_data.sentiment_analysis import get_entity_timeline, get_sentiment
from datasets.news_data.sentiment_common import _article_tone, _keyword_tone, _tone_compound
from datasets.news_data.sentiment_fetchers import _artlist, _csv_rows, _row_to_article

__all__ = [
    "_article_tone",
    "_artlist",
    "_csv_rows",
    "_keyword_tone",
    "_row_to_article",
    "_tone_compound",
    "get_entity_timeline",
    "get_sentiment",
]

# Backwards-compat re-exports (tests access these via ``sentiment.<name>``).
