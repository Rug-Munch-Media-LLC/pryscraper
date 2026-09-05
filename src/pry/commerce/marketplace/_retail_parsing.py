"""Embedded-JSON extraction and normalization for retail marketplace pages.

Thin re-export facade — implementation lives in:

- :mod:`pry.commerce.marketplace._retail_common` — shared helpers/normalization
- :mod:`pry.commerce.marketplace._retail_extract` — embedded-JSON extraction
- :mod:`pry.commerce.marketplace._retail_records` — record mapping + layered parse

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from pry.commerce.marketplace._retail_common import (  # noqa: F401
    _CURRENCY_MAP,
    _MONEY_RE,
    _PRICE_KEYS,
    _PRODUCT_ID_KEYS,
    _currency_from,
    _first_price,
    _has_price_signal,
    _looks_like_product,
    _price_value,
    _product_id_value,
    _rating_from,
    _seller_from,
    _stock_from,
    _walk_dicts,
)
from pry.commerce.marketplace._retail_extract import (  # noqa: F401
    _WINDOW_STATE_MARKERS,
    _embedded_state,
    _extract_window_state,
    _find_ld_product,
    _find_ld_search_items,
    _json_ld_objects,
    _ld_type,
)
from pry.commerce.marketplace._retail_records import (  # noqa: F401
    _ld_product_record,
    _og_record,
    _parse_product_page,
    _parse_search_page,
    _state_product_record,
    _walk_product_record,
    _walk_search_records,
)
