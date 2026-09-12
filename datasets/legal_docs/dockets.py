"""U.S. federal/state docket search — free CourtListener REST API v4.

CourtListener (free.law) publishes the RECAP / PACER docket database through
a public REST API. Anonymous access is rate-limited; a free API token can be
set via the ``PRY_COURTLISTENER_API_KEY`` env var and is sent as
``Authorization: Token <key>``. Without a token the API currently returns
401, which degrades every function to ``{}`` / ``[]`` (never raises) — the
module still works fully when a token is configured.

Contract
--------
* :func:`search_dockets` — async, never raises, returns a ``list`` (``[]``
  on failure). Searches dockets by full-text ``query``.
* :func:`get_docket` — async, never raises, returns a ``dict`` (``{}`` on
  failure). Fetches one docket by its CourtListener integer id; when the id
  is a Justia-style slug (non-numeric) it falls back to a Justia docket-page
  scrape for metadata.

Result shapes
-------------
``search_dockets`` returns a list of:

    {
        "id": 123456,
        "case_name": "United States v. Example Corp.",
        "docket_number": "1:22-cv-00001",
        "court": "dcd",                    # CourtListener court code
        "date_filed": "2022-01-15",
        "date_terminated": None,
        "nature_of_suit": "Contract",
        "cause": None,
        "url": "https://www.courtlistener.com/docket/123456/",
        "source": "courtlistener",
    }

``get_docket`` returns the same fields plus ``description``,
``jury_demand``, ``jurisdiction_type``, ``date_argued``,
``date_reargued``, ``date_last_filing``, ``appeal_from`` and ``panel``.

Free-API terms: https://www.courtlistener.com/api/rest/v4/ — identify
yourself with a descriptive User-Agent. Backoff: 2 retries, exponential
(0.4s -> 1.6s).

Implementation lives in ``dockets_http`` (transport), ``dockets_parsers``
(normalization + signature parsing) and ``dockets_search`` (orchestration);
this module is a stable re-export facade.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.legal_docs.dockets_http import _RETRY_CONFIG  # noqa: F401 — test seam
from datasets.legal_docs.dockets_search import get_docket, search_dockets

__all__ = ["get_docket", "search_dockets"]
