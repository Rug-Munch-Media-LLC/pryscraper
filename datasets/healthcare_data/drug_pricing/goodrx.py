"""GoodRx consumer-price fallback."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from datasets.healthcare_data.drug_pricing import config
from pry.engine.retry import async_retry

logger = logging.getLogger(__name__)


def _goodrx_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "drugs"


def _parse_goodrx_price(html: str) -> float | None:
    """Extract a consumer retail price from GoodRx JSON-LD (or None)."""
    for match in config._JSON_LD_RE.findall(html):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict) or str(node.get("@type") or "").lower() != "product":
                continue
            offers = node.get("offers")
            candidates: list[Any] = []
            if isinstance(offers, dict):
                candidates = [offers.get("price"), offers.get("lowPrice"), offers.get("highPrice")]
            elif isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        candidates.extend([offer.get("price"), offer.get("lowPrice")])
            for price in candidates:
                parsed = config._as_float(price)
                if parsed is not None:
                    return parsed
    return None


async def _try_goodrx(name: str) -> dict[str, Any] | None:
    """Best-effort GoodRx retail price. Returns None when gated/unavailable."""
    slug = _goodrx_slug(name)
    url = config._GOODRX_URL.format(slug=slug)

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0), headers=config._BROWSER_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
        price = _parse_goodrx_price(html)
        if price is None:
            raise ValueError("no parseable GoodRx price in page")
        return {
            "drug": name,
            "ndc": None,
            "price_per_unit": price,
            "price_type": "goodrx_retail",
            "source": "goodrx",
            "url": url,
        }

    try:
        return await async_retry(_one, config=config._RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None
