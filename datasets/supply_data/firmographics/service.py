"""Firmographics orchestration and stable public API."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

from datasets.supply_data.firmographics.hiring import _count_hiring_openings
from datasets.supply_data.firmographics.http import _fetch_html
from datasets.supply_data.firmographics.normalization import (
    _empty_firmographics,
    _normalize_slug,
)
from datasets.supply_data.firmographics.partner import _partner_firmographics
from datasets.supply_data.firmographics.signals import (
    _detect_industry,
    _detect_tech_stack,
    _extract_linkedin,
)
from datasets.supply_data.firmographics.website import (
    _find_website,
    _is_anti_bot_page,
)

logger = logging.getLogger(__name__)


async def get_company_firmographics(company: str) -> dict[str, Any]:
    """Return B2B firmographics for a company; never raises."""
    try:
        return await _get_company_firmographics(company)
    except Exception:
        logger.exception("supply_firmographics_crashed", extra={"company": company})
        return _empty_firmographics(company)


async def _get_company_firmographics(company: str) -> dict[str, Any]:
    name = company.strip()
    record = _empty_firmographics(name)
    if not name:
        return record
    slug = _normalize_slug(name)
    website = await _find_website(slug)
    record["website"] = website
    html = await _fetch_html(website) if website else None
    if html and _is_anti_bot_page(html):
        logger.warning(
            "firmographics_anti_bot",
            extra={"company": name, "website": website},
        )
        html = None
    if html:
        record["tech_stack"] = _detect_tech_stack(html)
        record["linkedin_url"] = _extract_linkedin(html)
        record["industry"] = _detect_industry(html)
    record["hiring_openings"] = await _count_hiring_openings(slug)
    record.update(await _partner_firmographics(name))
    return record
