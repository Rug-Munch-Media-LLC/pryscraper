"""Container freight intelligence — Freightos FBX rates + FMC agreements.

Pulls public, no-auth freight data for the Pry platform:

* :func:`get_container_rates` — 40ft container spot rates from the
  Freightos Baltic Index (FBX). The old public ``fbx.freightos.com/api``
  JSON endpoints are retired (they 301 to a marketing page), so the module
  reads the embedded JSON on the public FBX landing page
  (``window.frProductIntroTickerData`` / ``window.frProductIntroChartData``).
  When Freightos is unreachable the module falls back to scraping the
  Drewry World Container Index public Infogram embed.
* :func:`get_fmc_contracts` — agreements on file at the U.S. Federal
  Maritime Commission (FMC) Agreement Library. The FMC publishes no
  official public JSON API, so the module parses the public HTML index.

Contract
--------
* :func:`get_container_rates` — async, never raises, returns a ``list``
  (``[]`` on failure).
* :func:`get_fmc_contracts` — async, never raises, returns a ``list``
  (``[]`` on failure).

Result shapes
-------------
``get_container_rates`` returns a list of::

    {
        "route": "china-us-west-coast",   # slug; "fbx-composite" for the FBX
        "origin": "China",                # aggregate
        "destination": "US West Coast",
        "rate_40ft_usd": 7422.0,          # float or None
        "index_source": "freightos_fbx",  # or "drewry_wci"
        "date": "2026-08-14",             # ISO date
    }

``get_fmc_contracts`` returns a list of::

    {
        "id": "201353-003",               # FMC agreement number
        "carrier": "THE Alliance / Evergreen",
        "shipper": None,                  # FMC does not publish shippers
        "commodity": None,                # nor commodities for agreements
        "origin": "North Europe",         # parsed from agreement name, or None
        "destination": "US East Coast",
        "status": "Active",               # heuristic, see _derive_status
        "effective_date": "2021-03-15",   # ISO date or None
    }

Backoff: 2 retries, exponential (0.4s -> 1.6s).

Implementation lives in :mod:`rates_common` (constants + shared helpers),
:mod:`rates_parsers` (source parsers) and :mod:`rates_fetchers`
(source fetchers); this module is a thin re-export facade.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.freight_data.rates_common import (  # noqa: F401
    _AGREEMENT_KEYWORDS,
    _DREWRY_DATA_RE,
    _DREWRY_INFOGRAM,
    _DREWRY_SERIES,
    _FBX_CHART_RE,
    _FBX_LANES,
    _FBX_PAGE,
    _FBX_TICKER_RE,
    _FMC_INDEX,
    _HEADERS,
    _MAX_LIMIT,
    _REGION_HINTS,
    _RETRY_CONFIG,
    _ROUTE_ALIASES,
    _TIMEOUT,
    _cell_text,
    _fetch_text,
    _infogram_cell,
    _match_route,
    _parse_iso_date,
    _parse_money,
    _slug,
)
from datasets.freight_data.rates_fetchers import (  # noqa: F401
    _drewry_rates,
    _fbx_rates,
    _fetch_fmc_records,
    _filter_rate_records,
    _get_container_rates,
    _get_fmc_contracts,
    get_container_rates,
    get_fmc_contracts,
)
from datasets.freight_data.rates_parsers import (  # noqa: F401
    _derive_status,
    _drewry_records_from_page,
    _extract_carrier,
    _extract_trade_lanes,
    _fbx_records_from_page,
    _iter_infogram_series,
    _parse_fmc_html,
    _parse_infogram_rows,
)

__all__ = [
    "get_container_rates",
    "get_fmc_contracts",
]
