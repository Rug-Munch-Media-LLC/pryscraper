"""Live sports betting odds — The Odds API + ESPN + multi-source redundancy.

Public contract:
* :func:`get_odds` — async, never raises, returns a ``list`` (``[]`` on
  failure). One record per (event, bookmaker, market).
* :func:`get_event_odds` — async, never raises, returns a ``dict`` (``{}``
  on failure). Multi-sportsbook comparison for one event id.
* :func:`get_odds_multi` — async, never raises; merged multi-source set.
* :func:`supported_coverage` — sync sports x books x markets matrix.

Sources: The Odds API (``PRY_ODDS_API_KEY``, free tier), ESPN public
scoreboards (no key), plus redundancy sources (OddsPortal, Bovada,
BetOnline, 112-book registry) via the ``sources`` parameter. Sports,
markets, books, record shapes, caching (10s TTL, respx-bypassed) and
backoff details are documented on the sibling modules:
``odds_common`` / ``odds_fetchers`` / ``odds_parsers`` / ``odds_mapping``
/ ``odds_espn`` / ``odds_supplement`` / ``odds_multi``. This module
re-exports their surface so ``sports_data.odds`` is unchanged.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.sports_data.odds_common import (  # re-exported surface
    _BOOK_TITLES as _BOOK_TITLES,
    _BOOKS as _BOOKS,
    _CANONICAL_SPORTS as _CANONICAL_SPORTS,
    _DEFAULT_SPORTS as _DEFAULT_SPORTS,
    _ESPN_SCOREBOARD as _ESPN_SCOREBOARD,
    _MARKET_ALIASES as _MARKET_ALIASES,
    _MARKETS_ALL as _MARKETS_ALL,
    _MAX_LIMIT as _MAX_LIMIT,
    _ODDS_API_REGIONS as _ODDS_API_REGIONS,
    _ODDS_BASE as _ODDS_BASE,
    _SOURCE_NAMES as _SOURCE_NAMES,
    _SPORT_ALIASES as _SPORT_ALIASES,
    _SPORTS as _SPORTS,
    _american_to_decimal as _american_to_decimal,
    _api_key as _api_key,
    _as_text as _as_text,
    _bookmaker_params as _bookmaker_params,
    _canonical_book as _canonical_book,
    _event_label as _event_label,
    _nested as _nested,
    _normalize_markets as _normalize_markets,
    _parse_sources_param as _parse_sources_param,
    _record as _record,
    _resolve_sports as _resolve_sports,
    _to_float as _to_float,
)
from datasets.sports_data.odds_espn import (  # re-exported surface
    _espn_competitors as _espn_competitors,
    _espn_odds_to_comparison as _espn_odds_to_comparison,
    _espn_odds_to_records as _espn_odds_to_records,
)
from datasets.sports_data.odds_fetchers import (  # re-exported surface
    _CACHE_TTL as _CACHE_TTL,
    _HEADERS as _HEADERS,
    _RETRY_CONFIG as _RETRY_CONFIG,
    _TIMEOUT as _TIMEOUT,
    _cache_enabled as _cache_enabled,
    _cache_key as _cache_key,
    _clear_cache as _clear_cache,
    _espn_find_event as _espn_find_event,
    _espn_odds_for_league as _espn_odds_for_league,
    _fetch_json as _fetch_json,
    _fetch_uncached as _fetch_uncached,
    _http_cache as _http_cache,
    _monotonic as _monotonic,
)
from datasets.sports_data.odds_mapping import (  # re-exported surface
    _map_event_comparison as _map_event_comparison,
    _map_odds_event as _map_odds_event,
    _market_records as _market_records,
    _outcome_prices as _outcome_prices,
)
from datasets.sports_data.odds_multi import (  # re-exported surface
    _get_odds_multi as _get_odds_multi,
    get_odds_multi as get_odds_multi,
)
from datasets.sports_data.odds_parsers import (  # re-exported surface
    _get_event_odds as _get_event_odds,
    _get_odds as _get_odds,
    get_event_odds as get_event_odds,
    get_odds as get_odds,
    supported_coverage as supported_coverage,
)
from datasets.sports_data.odds_supplement import (  # re-exported surface
    _books_odds_for_sport as _books_odds_for_sport,
    _supplementary_records as _supplementary_records,
)
