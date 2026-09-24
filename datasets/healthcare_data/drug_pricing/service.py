"""Public drug-price orchestration."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from datasets.healthcare_data.drug_pricing import config
from datasets.healthcare_data.drug_pricing.goodrx import _try_goodrx
from datasets.healthcare_data.drug_pricing.nadac import _fetch_nadac_rows

logger = logging.getLogger(__name__)


async def get_drug_price(drug_name: str) -> dict[str, Any]:
    """Look up a US drug price by name (brand or generic).

    Args:
        drug_name: e.g. ``"atorvastatin"``, ``"Lipitor"``.

    Returns:
        Price record (see module docstring) or ``{}`` when no free source
        matched (unknown drug, network failure). Never raises.
    """
    try:
        return await _get_drug_price(drug_name)
    except Exception:
        logger.exception("health_drug_price_crashed", extra={"drug": drug_name})
        return {}


async def _get_drug_price(drug_name: str) -> dict[str, Any]:
    name = str(drug_name or "").strip()
    if not name:
        logger.warning("health_drug_price_empty")
        return {}
    needle = name.upper()
    rows = await _fetch_nadac_rows()
    candidates = [row for row in rows if needle in str(row.get("NDC Description") or "").upper()]
    if candidates:
        record = config._best_nadac_record(candidates, name)
        if record:
            return record
    # NADAC miss → best-effort GoodRx consumer-price scrape (often gated).
    goodrx = await _try_goodrx(name)
    if goodrx:
        return goodrx
    return {}
