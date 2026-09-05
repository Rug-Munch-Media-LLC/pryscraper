"""eBay marketplace adapter: Finding API search + Shopping API lookup.

Both APIs need a free app key set via the ``PRY_EBAY_API_KEY`` env var.
Without a key every eBay call degrades to ``[]`` / ``{}`` (never raises).
The app-key accessor (``_api_key``) is owned by the
:mod:`commerce_data.marketplaces` facade because tests monkeypatch it
there; it is resolved lazily at call time.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

from datasets.commerce_data.marketplaces_common import _elem_text, _to_float
from datasets.commerce_data.marketplaces_http import _fetch

logger = logging.getLogger(__name__)

_EBAY_FIND_URL = "https://svcs.ebay.com/services/search/FindingService/v1"
_EBAY_ITEM_URL = "https://open.api.ebay.com/shopping"
_EBAY_API_KEY_ENV = "PRY_EBAY_API_KEY"
_EBAY_NS = {"e": "http://www.ebay.com/marketplace/search/v1/services"}
_EBAY_ITEM_NS = {"s": "http://open.api.ebay.com/shopping"}


def _api_key() -> str:
    """Return the configured eBay app key, or '' when missing.

    Delegates to the facade's ``_api_key`` (late import) so test
    monkeypatches on ``marketplaces._api_key`` take effect.
    """
    from datasets.commerce_data.marketplaces import _api_key as _facade_api_key

    return _facade_api_key()


def _map_ebay_item(item: ET.Element) -> dict[str, Any] | None:
    """Map a Finding API ``<item>`` onto the canonical record."""
    item_id = _elem_text(item, "e:itemId", _EBAY_NS)
    title = _elem_text(item, "e:title", _EBAY_NS)
    if not item_id and not title:
        return None
    price_el = item.find("e:sellingStatus/e:convertedCurrentPrice", _EBAY_NS)
    if price_el is None:
        price_el = item.find("e:sellingStatus/e:currentPrice", _EBAY_NS)
    price = _to_float(price_el.text if price_el is not None else None)
    currency = price_el.get("currencyId") if price_el is not None else None
    seller = _elem_text(item, "e:sellerInfo/e:sellerUserName", _EBAY_NS)
    rating = _to_float(_elem_text(item, "e:sellerInfo/e:feedbackScore", _EBAY_NS))
    url = _elem_text(item, "e:viewItemURL", _EBAY_NS) or (
        f"https://www.ebay.com/itm/{item_id}" if item_id else ""
    )
    return {
        "id": item_id or "",
        "title": title or "",
        "price": price,
        "currency": currency,
        "seller": seller,
        "rating": rating,
        "url": url,
        "marketplace": "ebay",
    }


async def _ebay_search(query: str, limit: int) -> list[dict[str, Any]]:
    key = _api_key()
    if not key:
        logger.warning("ebay_search_no_api_key", extra={"env": _EBAY_API_KEY_ENV})
        return []
    params = {
        "OPERATION-NAME": "findItemsByKeywords",
        "SERVICE-VERSION": "1.13.0",
        "SECURITY-APPNAME": key,
        "GLOBAL-ID": "EBAY-US",
        "RESPONSE-DATA-FORMAT": "XML",
        "keywords": query,
        "paginationInput.entriesPerPage": str(min(limit, 100)),
        "sortOrder": "BestMatch",
    }
    raw = await _fetch(_EBAY_FIND_URL, params=params)
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)  # noqa: S314 - vetted HTTPS response; stdlib ET never resolves external entities
    except ET.ParseError:
        logger.warning("ebay_search_parse_failed")
        return []
    ack = root.findtext("e:ack", namespaces=_EBAY_NS) or ""
    if ack not in ("Success", "Warning"):
        return []
    out: list[dict[str, Any]] = []
    for item in root.findall("e:searchResult/e:item", _EBAY_NS):
        record = _map_ebay_item(item)
        if record:
            out.append(record)
        if len(out) >= limit:
            break
    return out


async def _ebay_get(product_id: str) -> dict[str, Any]:
    key = _api_key()
    if not key:
        logger.warning("ebay_get_no_api_key", extra={"env": _EBAY_API_KEY_ENV})
        return {}
    params = {
        "callname": "GetSingleItem",
        "appid": key,
        "ItemID": product_id,
        "responseencoding": "XML",
        "siteid": "0",
        "IncludeSelector": "Details",
    }
    raw = await _fetch(_EBAY_ITEM_URL, params=params)
    if not raw:
        return {}
    try:
        root = ET.fromstring(raw)  # noqa: S314 - vetted HTTPS response; stdlib ET never resolves external entities
    except ET.ParseError:
        logger.warning("ebay_get_parse_failed")
        return {}
    ack = root.findtext("s:Ack", namespaces=_EBAY_ITEM_NS) or ""
    if ack != "Success":
        return {}
    item = root.find("s:Item", _EBAY_ITEM_NS)
    if item is None:
        return {}
    item_id = _elem_text(item, "s:ItemID", _EBAY_ITEM_NS)
    title = _elem_text(item, "s:Title", _EBAY_ITEM_NS)
    if not item_id and not title:
        return {}
    price_el = item.find("s:ConvertedCurrentPrice", _EBAY_ITEM_NS)
    if price_el is None:
        price_el = item.find("s:CurrentPrice", _EBAY_ITEM_NS)
    price = _to_float(price_el.text if price_el is not None else None)
    currency = price_el.get("currencyID") if price_el is not None else None
    seller = _elem_text(item, "s:Seller/s:UserID", _EBAY_ITEM_NS)
    rating = _to_float(_elem_text(item, "s:Seller/s:FeedbackScore", _EBAY_ITEM_NS))
    url = _elem_text(item, "s:ViewItemURLForNaturalSearch", _EBAY_ITEM_NS) or (
        f"https://www.ebay.com/itm/{item_id}" if item_id else ""
    )
    return {
        "id": item_id or "",
        "title": title or "",
        "price": price,
        "currency": currency,
        "seller": seller,
        "rating": rating,
        "url": url,
        "marketplace": "ebay",
    }
