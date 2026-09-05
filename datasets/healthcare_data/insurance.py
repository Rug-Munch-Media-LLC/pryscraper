"""Insurance quotes — feasibility-flagged, with public rate-table fallback.

Car/home insurance **quote forms** (Progressive, Geico, State Farm, ...) are
captcha/JS-gated: they require a browser session to fill multi-step forms and
return live quotes. A plain HTTP scrape of those forms is not reliable. This
module is honest about that — :func:`get_insurance_quotes` probes the known
quote forms, detects the gating, and returns a documented
``{"available": False, "reason": ...}`` payload instead of fabricating
quotes.

What *is* scrapeable without auth or a browser is **public rate tables** —
aggregated average-premium tables published on static pages, implemented via
:func:`get_insurance_rate_table` (III.org state-by-state tables).

Contract
--------
* :func:`get_insurance_quotes` — async, never raises. Returns
  ``{"available": True, ...}`` or the documented ``{"available": False,
  "reason": ...}`` payload. Never returns fabricated premiums.
* :func:`get_insurance_rate_table` — async, never raises, returns a
  ``list`` (``[]`` on failure). Public aggregate rate-table data.

Quote record shape: ``{"provider": ..., "premium": float, "deductible":
None, "url": ...}``. Rate-table record shape: ``{"state": ..., "premium":
float, "source": "public_rate_table", "url": ...}``.

Backoff: 1 retry for quote probes (short timeout), 2 for the rate table.
Internals live in the ``insurance_common`` / ``insurance_fetchers`` /
``insurance_parsers`` siblings; this module re-exports them so the
``healthcare_data.insurance`` surface is unchanged.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from datasets.healthcare_data.insurance_common import (  # re-exported surface
    _BROWSER_HEADERS as _BROWSER_HEADERS,
    _COVERAGE_TYPES as _COVERAGE_TYPES,
    _GATING_MARKERS as _GATING_MARKERS,
    _JSON_LD_RE as _JSON_LD_RE,
    _MONEY_RE as _MONEY_RE,
    _PRICE_RE as _PRICE_RE,
    _PROBE_RETRY as _PROBE_RETRY,
    _PROBE_TIMEOUT as _PROBE_TIMEOUT,
    _PROVIDERS as _PROVIDERS,
    _RATE_PAGES as _RATE_PAGES,
    _RETRY_CONFIG as _RETRY_CONFIG,
    _STATE_ABBR as _STATE_ABBR,
    _TIMEOUT as _TIMEOUT,
    _as_money as _as_money,
    _contains_any as _contains_any,
    _is_gated as _is_gated,
    _looks_numeric as _looks_numeric,
    _match_state as _match_state,
    _normalize_cell as _normalize_cell,
    _normalize_state as _normalize_state,
    _NotScrapeable as _NotScrapeable,
    _parse_quote_page as _parse_quote_page,
)
from datasets.healthcare_data.insurance_fetchers import (  # re-exported surface
    _fetch_html as _fetch_html,
    _get_insurance_quotes as _get_insurance_quotes,
    _get_insurance_rate_table as _get_insurance_rate_table,
    _probe_provider as _probe_provider,
    get_insurance_quotes as get_insurance_quotes,
    get_insurance_rate_table as get_insurance_rate_table,
)
from datasets.healthcare_data.insurance_parsers import (  # re-exported surface
    _parse_rate_table as _parse_rate_table,
)
